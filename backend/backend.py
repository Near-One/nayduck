import datetime
import json
import os
import traceback
import typing

import flask
import flask.json
import flask_apscheduler
import flask_cors
import werkzeug.exceptions
import werkzeug.wrappers

from . import auth
from . import scheduler
from . import backend_db

NAYDUCK_UI = (os.getenv('NAYDUCK_UI') or
              'http://nayduck.eastus.cloudapp.azure.com:3000')

app = flask.Flask(__name__)
flask_cors.CORS(app, resources={'/api/.*': {'origins': [NAYDUCK_UI]}})

sched = flask_apscheduler.APScheduler()
sched.init_app(app)
sched.start()


def jsonify(data: typing.Any) -> flask.Response:
    """Converts data to a Response holding JSON data.

    If the data is not None, the response will have 200 OK status code;
    otherwise, None data results in a 404 Not Found response.  In either case,
    the content will be JSON data and content-type will be set to
    application/json.

    Args:
        data: Data to include in response.  Anything that can be serialised to
            JSON works.
    Returns:
        A Response object.
    """

    def default(obj: typing.Any) -> typing.Any:
        if isinstance(obj, datetime.datetime):
            if obj.utcoffset() is None:
                obj = obj.replace(tzinfo=datetime.timezone.utc)
            return int(obj.timestamp() * 1000)
        raise TypeError(
            f'Object of type {type(obj).__name__} is not JSON serialisable')

    response = json.dumps(data,
                          ensure_ascii=False,
                          check_circular=False,
                          separators=(',', ':'),
                          default=default)
    return flask.Response(response=response,
                          status=404 if data is None else 200,
                          mimetype='application/json')


@app.route('/api/runs', methods=['GET'])
def get_runs() -> flask.Response:
    with backend_db.BackendDB() as server:
        all_runs = server.get_all_runs()
    return jsonify(all_runs)


@app.route('/api/run/<int:run_id>', methods=['GET'])
def get_a_run(run_id: int) -> flask.Response:
    with backend_db.BackendDB() as server:
        a_run = server.get_one_run(run_id)
    return jsonify(a_run)


@app.route('/api/test/<int:test_id>', methods=['GET'])
def get_a_test(test_id: int) -> flask.Response:
    with backend_db.BackendDB() as server:
        a_test = server.get_one_test(test_id)
    return jsonify(a_test)


@app.route('/api/build/<int:build_id>', methods=['GET'])
def get_build_info(build_id: int) -> flask.Response:
    with backend_db.BackendDB() as server:
        a_test = server.get_build_info(build_id)
    return jsonify(a_test)


@app.route('/api/test/<int:test_id>/history', methods=['GET'])
def test_history(test_id: int) -> flask.Response:
    with backend_db.BackendDB() as server:
        history = server.get_test_history_by_id(test_id)
    return jsonify(history)


@app.route('/api/test/<int:test_id>/history/<path:branch>', methods=['GET'])
def branch_history(test_id: int, branch: str) -> flask.Response:
    with backend_db.BackendDB() as server:
        history = server.get_histoty_for_base_branch(test_id, branch)
    return jsonify(history)


@app.route('/api/run/<int:run_id>/cancel', methods=['POST'])
def cancel_the_run(run_id: int) -> flask.Response:
    with backend_db.BackendDB() as server:
        count = server.cancel_the_run(run_id)
    return jsonify(count)


@app.route('/api/run/new', methods=['POST'])
@flask_cors.cross_origin(origins=[])
@auth.authenticated
def new_run(login: str) -> flask.Response:
    with backend_db.BackendDB() as server:
        try:
            run_id = scheduler.Request.from_json(
                flask.request.get_json(force=True),
                requester=login).schedule(server)
            url = f'Success. {NAYDUCK_UI}/#/run/{run_id}'
            response: typing.Dict[str, typing.Any] = {
                'code': 0,
                'response': f'Success. {url}'
            }
        except scheduler.Failure as ex:
            response = ex.to_response()
        except Exception as ex:
            traceback.print_exc()
            response = scheduler.Failure(ex).to_response()
        return jsonify(response)


def schedule_nightly_run_check(delta: datetime.timedelta) -> None:

    def check() -> None:
        schedule_nightly_run_check(
            max(scheduler.schedule_nightly_run(),
                datetime.timedelta(minutes=3)))

    sched.add_job(func=check,
                  trigger='date',
                  id='nightly_run_check',
                  misfire_grace_time=None,
                  coalesce=True,
                  run_date=(datetime.datetime.now() + delta))


@app.route('/logs/<any("test","build"):kind>/<int:obj_id>/<log_type>')
def get_test_log(kind: str, obj_id: int, log_type: str) -> flask.Response:
    gzip_ok = 'gzip' in flask.request.headers.get('accept-encoding', '')
    if kind == 'test':
        getter = lambda db, gzip_ok: db.get_test_log(obj_id, log_type, gzip_ok)
    elif log_type in ('stderr', 'stdout'):
        getter = lambda db, gzip_ok: db.get_build_log(obj_id, log_type, gzip_ok)
    else:
        flask.abort(404)
    with backend_db.BackendDB() as server:
        try:
            blob, compressed = getter(server, gzip_ok)  # type: ignore
        except KeyError:
            flask.abort(404)
    response = flask.make_response(blob, 200)
    response.headers['vary'] = 'Accept-Encoding'
    response.headers['cache-control'] = (
        f'public, max-age={365 * 24 * 3600}, immutable')
    if log_type.endswith('.gz'):
        content_type = 'application/gzip'
    else:
        content_type = 'text/plain; charset=utf-8'
    response.headers['content-type'] = content_type
    if compressed:
        response.headers['content-encoding'] = 'gzip'
    return response


@app.route('/login/<any("cli","web"):mode>', methods=['GET'])
def login_redirect(mode: str) -> werkzeug.wrappers.Response:
    try:
        code = auth.AuthCode.from_request(flask.request)
        if code.verify():
            return _login_response(code.code, mode == 'web')
    except werkzeug.exceptions.HTTPException:
        pass
    return flask.redirect(auth.generate_redirect(mode))


@app.route('/login/code', methods=['GET'])
def login_code() -> werkzeug.wrappers.Response:
    try:
        code, is_web = auth.get_code(state=flask.request.args.get('state'),
                                     code=flask.request.args.get('code'))
    except auth.AuthFailed as ex:
        return flask.Response(str(ex), 403, mimetype='text/plain')
    return _login_response(code.code, is_web)


def _login_response(code: str, is_web: bool) -> werkzeug.wrappers.Response:
    if is_web:
        response = flask.redirect(f'{NAYDUCK_UI}/#{auth.CODE_KEY}={code}')
    else:
        text = f'''<!DOCTYPE html><html lang=en>
<title>NayDuck Authorisation Code</title>
<style>
html, body {{ width: 100%; height: 100%; padding: 0; margin: 0; }}
body {{ display: flex; align-items: center; justify-content: center;\
 font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Oxygen, Ubuntu, Cantarell, Fira Sans, Droid Sans, Helvetica Neue, sans-serif; }}
div {{ width: auto; padding: 2em; margin: 0; }}
span {{ display: block; margin: 1em 0; font-size: 0.8em;\
 font-family: DejaVu Sans Mono, Source Code Pro, Liberation Mono, Courier New, monospace; }}
</style>
<div>
  Your NayDuck authorisation code is:
  <span>{code}</span>
  Copy it (including the user name at the front) and paste into the nayduck tool
  prompt.
</div>'''
        response = flask.Response(text,
                                  200,
                                  mimetype='text/html',
                                  headers=(('Content-Language', 'en'),))
    auth.add_cookie(response, code)
    return response


@app.route('/logout', methods=['GET'])
def logout() -> werkzeug.wrappers.Response:
    response = flask.redirect(flask.request.referrer or NAYDUCK_UI)
    response.headers['clear-site-data'] = '*'
    response.delete_cookie(auth.CODE_KEY)
    return response


if __name__ == '__main__':
    schedule_nightly_run_check(datetime.timedelta(seconds=10))
    app.run(debug=False, host='0.0.0.0', port=5005)
