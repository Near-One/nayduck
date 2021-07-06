import os
import typing
import traceback

import requests
import flask
from rc import bash

from db import SchedulerDB

app = flask.Flask(__name__)

app.config['TEMPLATES_AUTO_RELOAD'] = True


class Failure(Exception):
    """An exception indicating failure of the request_a_run request."""

    def __init__(self, response: typing.Any) -> None:
        super().__init__('Failure. {}'.format(response))

    def to_response(self) -> typing.Dict[str, typing.Union[int, str]]:
        """Returns a JSON object intended to return to the caller on failure."""
        return {'code': 1, 'response': self.args[0]}


def request_a_run_impl(request_json: typing.Dict[str, typing.Any]) -> int:
    """Starts a test run based on the JSON request.

    Args:
        request_json: The JSON object describing the request client is making.
    Returns:
        Numeric identifier of the scheduled test run.
    Raises:
        Failure: on any kind of error.
    """
    # if not request_json['token']:
    #     raise Failure('Your client is too old. NayDuck requires Github auth. '
    #                   'Sync your client to head.')
    server = SchedulerDB()
    if 'token' in request_json:
        github_login = server.get_github_login(request_json['token'])
        if not github_login:
            raise Failure('NayDuck token is not found. Do not try to fake it.')
        if github_login != 'NayDuck':
            github_req = f'''https://api.github.com/users/{github_login}/orgs'''
            response = requests.get(github_req)
            if not any(org.get('login') in ('nearprotocol', 'near')
                       for org in response.json()):
                raise Failure(f'{github_login} is not part of '
                              'NearProtocol or Near orgs.')
    if not request_json['branch'] or not request_json['sha']:
        raise Failure('Branch and/or git sha were not provided.')

    requester = request_json.get('requester', 'unknown')

    fetch = bash(f'''
            rm -rf nearcore
            git clone https://github.com/near/nearcore
            cd nearcore
            git fetch 
            git checkout {request_json['sha']}
    ''')
    if fetch.returncode != 0:
        raise Failure(fetch.stderr)

    user = bash(f'''
        cd nearcore
        git log --format='%ae' {request_json['sha']}^!
    ''').stdout
    title = bash(f'''
        cd nearcore
        git log --format='%s' {request_json['sha']}^!
    ''').stdout
    tests = []
    for test in request_json['tests']:
        spl = test.split(maxsplit=1)
        if spl and spl[0][0] != '#':
            if len(spl) > 1 and spl[0].isnumeric():
                tests.extend(spl[1:] * int(spl[0]))
            else:
                tests.append(test.strip())
    return server.scheduling_a_run(branch=request_json['branch'],
                                   sha=request_json['sha'],
                                   user=user.split('@')[0],
                                   title=title,
                                   tests=tests,
                                   requester=requester)


@app.route('/request_a_run', methods=['POST', 'GET'])
def request_a_run():
    request_json = flask.request.get_json(force=True)
    try:
        run_id = request_a_run_impl(request_json)
        url = '{}/#/run/{}'.format(os.getenv('NAYDUCK_UI'), run_id)
        response = {'code': 0, 'response': 'Success. ' + url}
    except Failure as ex:
        response = ex.to_response()
    except Exception as ex:
        traceback.print_exc()
        response = Failure(ex).to_response()
    return flask.jsonify(response)


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
    
