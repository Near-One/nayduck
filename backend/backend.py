import datetime
import gzip
import json
import pathlib
import time
import traceback
import typing

import flask
import flask.json
import flask_apscheduler
import werkzeug.exceptions
import werkzeug.wrappers

from . import auth
from . import scheduler
from . import backend_db

app = flask.Flask(__name__, static_folder=None)

sched = flask_apscheduler.APScheduler()
sched.init_app(app)
sched.start()

STATIC_FILES = pathlib.Path(app.root_path).parent / 'frontend' / 'build'


def can_gzip(request: flask.Request) -> bool:
    """Returns whether user agent accepts gzip content encoding."""
    return 'gzip' in request.headers.get('accept-encoding', '')


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
                          default=default).encode('utf-8')
    status = 404 if data is None else 200
    headers = {}
    if len(response) > 100 and can_gzip(flask.request):
        response = gzip.compress(response, 6)
        headers['Content-Encoding'] = 'gzip'
    return flask.Response(response=response,
                          status=status,
                          mimetype='application/json',
                          headers=headers)


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
@auth.authorised
def cancel_the_run(run_id: int) -> flask.Response:
    with backend_db.BackendDB() as server:
        count = server.cancel_the_run(run_id)
    return jsonify(count)


@app.route('/api/run/new', methods=['POST'])
@auth.authorised
def new_run(login: str) -> flask.Response:
    with backend_db.BackendDB() as server:
        try:
            run_id = scheduler.Request.from_json(
                flask.request.get_json(force=True),
                requester=login).schedule(server)
            url = f'Success.  {flask.request.url_root}#/run/{run_id}'
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
    gzip_ok = can_gzip(flask.request)
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


@app.route('/login', defaults={'mode': 'web'}, methods=['GET'])
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
        response = flask.redirect('/')
    else:
        text = f'''<!DOCTYPE html><html lang=en>
<title>NayDuck Authorisation Code</title>
<style>
html, body {{ width: 100%; height: 100%; padding: 0; margin: 0; }}
body {{ display: flex; align-items: center; justify-content: center;\
 font-family: Inter, Roboto, Fira Sans, Helvetica Neue, Helvetica, sans-serif; }}
section {{ width: auto; padding: 2em; margin: 0; }}
pre {{ display: block; margin: 1em 0; font-size: 0.8em;\
 font-family: Source Code Pro, DejaVu Sans Mono, Courier New, monospace; }}
</style>
<section>
  <p>Your NayDuck authorisation code is:
  <pre>{code}</pre>
  <p>Copy it (including the user name at the front) and paste into the nayduck
  tool prompt.
</section>'''
        response = flask.Response(text, 200)
        response.content_type = 'text/html; charset=utf-8'
    auth.add_cookie(response, code)
    return response


class StaticFile:

    def __init__(self, filename: str) -> None:
        self._path = STATIC_FILES / filename
        self._mtime = self._path.stat().st_mtime
        self._data = self._load(self._path)

    @classmethod
    def _load(cls, path: pathlib.Path) -> typing.Tuple[bytes, bytes]:
        contents = path.read_bytes()
        compressed = gzip.compress(contents, 9)
        return contents, compressed

    def get(self, compressed: bool) -> typing.Tuple[bytes, int, str]:
        mtime = self._path.stat().st_mtime
        if mtime != self._mtime:
            self._data = self._load(self._path)
        etag = (int(self._mtime).to_bytes(4, 'little') +
                len(self._data[0]).to_bytes(4, 'little')).hex()
        return self._data[int(compressed)], int(self._mtime), etag


INDEX_HTML = StaticFile('index.html')


@app.route('/', defaults={'path': 'index.html'}, methods=['GET'])
@app.route('/<path:path>', methods=['GET'])
def serve_static(path: str) -> werkzeug.wrappers.Response:
    if path != 'index.html':
        return flask.send_from_directory(str(STATIC_FILES),
                                         path,
                                         max_age=24 * 3600)

    # Handle index.html individually to support gzip compression.  Since we’re
    # bundling everything in the index.html file it’s by far the largest so the
    # compression does matter.
    compressed = can_gzip(flask.request)
    body, mtime, etag = INDEX_HTML.get(compressed)
    res = flask.Response(body, 200)
    res.set_etag(etag)
    res.cache_control.max_age = 3600
    res.content_length = len(body)
    res.content_type = 'text/html; charset=utf-8'
    res.expires = int(time.time() + 3600)
    res.last_modified = mtime
    res.vary = 'accept-encoding'
    if compressed:
        res.content_encoding = 'gzip'
    return typing.cast(werkzeug.wrappers.Response,
                       res.make_conditional(flask.request))


if __name__ == '__main__':
    schedule_nightly_run_check(datetime.timedelta(seconds=10))
    app.run(debug=False, host='0.0.0.0', port=5005)
