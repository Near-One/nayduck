import os
import pathlib
import shlex
import shutil
import subprocess
import typing
import traceback

import requests
import flask

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


def run(*cmd: str, cwd: typing.Optional[pathlib.Path]=None) -> bytes:
    """Executes a command; returns its output as "bytes"; raises on failure.

    Args:
        cmd: The command to execute as a positional arguments of command line
            arguments.  Running through shell is not supported by design since
            it too easily leads to vulnerabilities.
    Returns:
        A bytes containing the standard output of the command.
    Raises:
        Failure: if the command fails to execute (e.g. command not found) or
            returns non-zero exit status.
    """
    try:
        return subprocess.check_output(cmd, cwd=cwd, input=None,
                                       stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as ex:
        command = ' '.join(shlex.quote(arg) for arg in cmd)
        stderr = ex.stderr.decode('utf-8', 'replace')
        raise Failure('Command <{}> terminated with exit code {}:\n{}'.format(
            command, ex.returncode, stderr)) from ex


def update_repo() -> pathlib.Path:
    """Fetches the latest code from nearcore repository and returns path to it.

    The command clones the nearcore repository to ~/nearcore.git directory and
    returns path to it (i.e. Path representing ~/nearcore.git).  If the
    directory already exists, rather than cloning the repository anew, updates
    the existing local repository.  The end result is the same.  If there's an
    error updating the existing repository, it is deleted and created anew as if
    it was never there.

    Returns:
        Path to the local clone of the nearcore repository.  The path is to
        a bare repository, i.e. the repository does not have a work tree.
    Raises:
        Failure: if cloning of the remote repository fails.
    """
    home_dir = pathlib.Path.home()
    repo_dir = home_dir / 'nearcore.git'

    if repo_dir.is_dir():
        try:
            run('git', 'remote', 'update', '--prune', cwd=repo_dir)
            return repo_dir
        except Failure as ex:
            print(ex.args[0])
        shutil.rmtree(repo_dir)

    run('git', 'clone', '--mirror', 'https://github.com/near/nearcore',
        cwd=home_dir)
    return repo_dir


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
    repo_dir = update_repo()
    sha, user, title = run(
        'git', 'log', '--format=%H\n%ae\n%s', '-n1', request_json['sha'],
        cwd=repo_dir).decode('utf-8', errors='replace').splitlines()
    tests = []
    for test in request_json['tests']:
        spl = test.split(maxsplit=1)
        if spl and spl[0][0] != '#':
            if len(spl) > 1 and spl[0].isnumeric():
                tests.extend(spl[1:] * int(spl[0]))
            else:
                tests.append(test.strip())
    return server.scheduling_a_run(branch=request_json['branch'], sha=sha,
                                   user=user.split('@')[0], title=title,
                                   tests=tests, requester=requester)


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
    
