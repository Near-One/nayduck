import datetime
import os
import traceback
import typing

import flask
import flask.json
import flask_apscheduler
import flask_cors
import werkzeug.exceptions

from . import auth
from . import scheduler
from . import ui_db

NAYDUCK_UI = (os.getenv('NAYDUCK_UI') or
              'http://nayduck.eastus.cloudapp.azure.com:3000')

app = flask.Flask(__name__)
flask_cors.CORS(app, origins=NAYDUCK_UI)

sched = flask_apscheduler.APScheduler()
sched.init_app(app)
sched.start()


class JSONEncoder(flask.json.JSONEncoder):
    """Custom JSON encoder which encodes datetime as millisecond timestamp."""

    def default(self, o):
        if isinstance(o, datetime.datetime):
            if o.utcoffset() is None:
                o = o.replace(tzinfo=datetime.timezone.utc)
            return int(o.timestamp() * 1000)
        return super().default(o)


app.json_encoder = JSONEncoder


@app.route('/api/runs', methods=['GET'])
def get_runs():
    with ui_db.UIDB() as server:
        all_runs = server.get_all_runs()
    return flask.jsonify(all_runs)


@app.route('/api/run/<int:run_id>', methods=['GET'])
def get_a_run(run_id: int):
    with ui_db.UIDB() as server:
        a_run = server.get_one_run(run_id)
    return flask.jsonify(a_run)


@app.route('/api/test/<int:test_id>', methods=['GET'])
def get_a_test(test_id: int):
    with ui_db.UIDB() as server:
        a_test = server.get_one_test(test_id)
    return flask.jsonify(a_test)


@app.route('/api/build/<int:build_id>', methods=['GET'])
def get_build_info(build_id: int):
    with ui_db.UIDB() as server:
        a_test = server.get_build_info(build_id)
    return flask.jsonify(a_test)


@app.route('/api/test/<int:test_id>/history', methods=['GET'])
def test_history(test_id: int):
    with ui_db.UIDB() as server:
        history = server.get_test_history_by_id(test_id)
    return flask.jsonify(history)


@app.route('/api/test/<int:test_id>/history/<path:branch>', methods=['GET'])
def branch_history(test_id: int, branch: str):
    with ui_db.UIDB() as server:
        history = server.get_histoty_for_base_branch(test_id, branch)
    return flask.jsonify(history)


@app.route('/api/run/<int:run_id>/cancel', methods=['POST'])
def cancel_the_run(run_id: int):
    with ui_db.UIDB() as server:
        server.cancel_the_run(run_id)
    return flask.jsonify({})


# TODO(#17): Deprecated in favour of /api/run/new.
@app.route('/request_a_run', methods=['POST'])
@flask_cors.cross_origin(origins=[])
def request_a_run():
    request_json = flask.request.get_json(force=True)
    try:
        request = scheduler.Request.from_json_request(request_json)
        with ui_db.UIDB() as server:
            run_id = request.schedule(server)
        url = f'Success. {NAYDUCK_UI}/#/run/{run_id}'
        response = {'code': 0, 'response': f'Success. {url}'}
    except scheduler.Failure as ex:
        response = ex.to_response()
    except Exception as ex:
        traceback.print_exc()
        response = scheduler.Failure(ex).to_response()
    return flask.jsonify(response)


@app.route('/api/run/new', methods=['POST'])
@flask_cors.cross_origin(origins=[])
@auth.authenticated
def new_run(login: str) -> flask.Response:
    with ui_db.UIDB() as server:
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
        return flask.jsonify(response)


def schedule_nightly_run_check(delta: datetime.timedelta):

    def check():
        schedule_nightly_run_check(
            max(scheduler.schedule_nightly_run(),
                datetime.timedelta(minutes=3)))

    sched.add_job(func=check,
                  trigger='date',
                  id='nightly_run_check',
                  misfire_grace_time=None,
                  coalesce=True,
                  run_date=(datetime.datetime.now() + delta))


@app.route('/login/<any("cli","web"):mode>', methods=['GET'])
def login_redirect(mode: str) -> flask.Response:
    try:
        code = auth.AuthCode.from_request(flask.request)
        if code.verify():
            return _login_response(code.code, mode == 'web')
    except werkzeug.exceptions.HTTPException:
        pass
    return flask.redirect(auth.generate_redirect(mode))


@app.route('/login/code', methods=['GET'])
def login_code() -> flask.Response:
    try:
        code, is_web = auth.get_code(state=flask.request.args.get('state'),
                                     code=flask.request.args.get('code'))
    except auth.AuthFailed as ex:
        return flask.Response(str(ex), 403, mimetype='text/plain')
    return _login_response(code.code, is_web)


def _login_response(code: str, is_web: bool) -> flask.Response:
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
        response = flask.Response(text, 200, mimetype='text/html',
                                  headers=(('Content-Language', 'en'),))
    auth.add_cookie(response, code)
    return response


@app.route('/logout', methods=['GET'])
def logout() -> flask.Response:
    response = flask.redirect(flask.request.referrer or NAYDUCK_UI)
    response.headers['clear-site-data'] = '*'
    response.delete_cookie(auth.CODE_KEY)
    return response


if __name__ == '__main__':
    schedule_nightly_run_check(datetime.timedelta(seconds=10))
    app.run(debug=False, host='0.0.0.0', port=5005)
