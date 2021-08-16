import datetime
import os
import traceback

import flask
import flask.json
import flask_apscheduler
import flask_cors

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


@app.route('/api/get_auth_code/<string:login>', methods=['GET'])
def get_auth_code(login: str):
    with ui_db.UIDB() as server:
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


if __name__ == '__main__':
    schedule_nightly_run_check(datetime.timedelta(seconds=10))
    app.run(debug=False, host='0.0.0.0', port=5005)
