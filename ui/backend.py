import os
import traceback
import typing

import flask
import flask_cors

from ui_db import UIDB
import scheduler


NAYDUCK_UI = (os.getenv('NAYDUCK_UI') or
              'http://nayduck.eastus.cloudapp.azure.com:3000')

app = flask.Flask(__name__)
flask_cors.CORS(app, origins=NAYDUCK_UI)


def get_int(req: typing.Any, key: str) -> int:
    """Gets an integer field from the JSON request.

    The value may be of any type which can be converted into an int by calling
    `int(value)`.

    Args:
        req: The JSON request object.
        key: The key to get from the request object.
    Raises:
        HTTPException: if req is not a dictionary, is missing the key or the
           value of the key is not convertible into an integer.
    """
    try:
        return int(req[key])
    except Exception:
        flask.abort(400)
        raise  # just to silence pylint


def get_str(req: typing.Any, key: str) -> str:
    """Gets a string field from the JSON request.

    Args:
        req: The JSON request object.
        key: The key to get from the request object.
    Raises:
        HTTPException: if req is not a dictionary, is missing the key or the
           value is not a string.
    """
    try:
        value = req[key]
        if not isinstance(value, str):
            flask.abort(400)
    except Exception:
        flask.abort(400)
        raise  # just to silence pylint
    return value


@app.route('/', methods=['GET'])
def get_runs():
    with UIDB() as server:
        all_runs = server.get_all_runs()
    return flask.jsonify(all_runs)


@app.route('/run', methods=['POST', 'GET'])
def get_a_run():
    request_json = flask.request.get_json(force=True)
    run_id = get_int(request_json, 'run_id')
    with UIDB() as server:
        a_run = server.get_one_run(run_id)
    return flask.jsonify(a_run)


@app.route('/test', methods=['POST', 'GET'])
def get_a_test():
    request_json = flask.request.get_json(force=True)
    test_id = get_int(request_json, 'test_id')
    with UIDB() as server:
        a_test = server.get_one_test(test_id)
    return flask.jsonify(a_test)


@app.route('/build', methods=['POST', 'GET'])
def get_build_info():
    request_json = flask.request.get_json(force=True)
    build_id = get_int(request_json, 'build_id')
    with UIDB() as server:
        a_test = server.get_build_info(build_id)
    return flask.jsonify(a_test)


@app.route('/test_history', methods=['POST', 'GET'])
def test_history():
    request_json = flask.request.get_json(force=True)
    test_id = get_int(request_json, 'test_id')
    with UIDB() as server:
        history = server.get_test_history_by_id(test_id)
    return flask.jsonify(history)


@app.route('/branch_history', methods=['POST', 'GET'])
def branch_history():
    request_json = flask.request.get_json(force=True)
    test_id = get_int(request_json, 'test_id')
    branch = get_str(request_json, 'branch')
    with UIDB() as server:
        history = [server.get_histoty_for_base_branch(test_id, branch)]
    return flask.jsonify(history)


@app.route('/cancel_the_run', methods=['POST', 'GET'])
def cancel_the_run():
    request_json = flask.request.get_json(force=True)
    run_id = get_int(request_json, 'run_id')
    with UIDB() as server:
        server.cancel_the_run(run_id)
    return flask.jsonify({})


@app.route('/get_auth_code', methods=['POST', 'GET'])
def get_auth_code():
    request_json = flask.request.get_json(force=True)
    login = get_str(request_json, 'github_login')
    with UIDB() as server:
        code = server.get_auth_code(login)
    return flask.jsonify({'code': code})


@app.route('/request_a_run', methods=['POST'])
@flask_cors.cross_origin(origins=[])
def request_a_run():
    request_json = flask.request.get_json(force=True)
    try:
        run_id = scheduler.request_a_run_impl(request_json)
        url = f'Success. {NAYDUCK_UI}/#/run/{run_id}'
        response = {'code': 0, 'response': f'Success. {url}'}
    except scheduler.Failure as ex:
        response = ex.to_response()
    except Exception as ex:
        traceback.print_exc()
        response = scheduler.Failure(ex).to_response()
    return flask.jsonify(response)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5005)
