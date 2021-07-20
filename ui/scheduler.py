import pathlib
import shlex
import shutil
import subprocess
import typing

import requests

from ui_db import UIDB


class Failure(Exception):
    """An exception indicating failure of the request_a_run request."""

    def __init__(self, response: typing.Any) -> None:
        super().__init__('Failure. {}'.format(response))

    def to_response(self) -> typing.Dict[str, typing.Union[int, str]]:
        """Returns a JSON object intended to return to the caller on failure."""
        return {'code': 1, 'response': self.args[0]}


def _run(*cmd: str, cwd: typing.Optional[pathlib.Path]=None) -> bytes:
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


def _update_repo() -> pathlib.Path:
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
            _run('git', 'remote', 'update', '--prune', cwd=repo_dir)
            return repo_dir
        except Failure as ex:
            print(ex.args[0])
        shutil.rmtree(repo_dir)

    _run('git', 'clone', '--mirror', 'https://github.com/near/nearcore',
         cwd=home_dir)
    return repo_dir


def _verify_token(server: UIDB,
                  request_json: typing.Dict[str, typing.Any]) -> None:
    """Verifies if request has correct token; raises Failure if not."""
    token = request_json.get('token')
    if token is None:
    #     raise Failure('Your client is too old. NayDuck requires Github auth. '
    #                   'Sync your client to head.')
        return
    github_login = server.get_github_login(token)
    if not github_login:
        raise Failure('Invalid NayDuck token.')
    if github_login == 'NayDuck':
        return
    github_req = f'https://api.github.com/users/{github_login}/orgs'
    response = requests.get(github_req)
    if not any(org.get('login') in ('nearprotocol', 'near')
               for org in response.json()):
        raise Failure(f'{github_login} is not part of '
                      'NearProtocol or Near organisations.')


def request_a_run_impl(request_json: typing.Dict[str, typing.Any]) -> int:
    """Starts a test run based on the JSON request.

    Args:
        request_json: The JSON object describing the request client is making.
    Returns:
        Numeric identifier of the scheduled test run.
    Raises:
        Failure: on any kind of error.
    """
    server = UIDB()
    _verify_token(server, request_json)
    if not request_json['branch'] or not request_json['sha']:
        raise Failure('Branch and/or git sha were not provided.')

    requester = request_json.get('requester', 'unknown')
    repo_dir = _update_repo()
    sha, user, title = _run(
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
    return server.schedule_a_run(branch=request_json['branch'], sha=sha,
                                 user=user.split('@')[0], title=title,
                                 tests=tests, requester=requester)
