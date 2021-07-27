import pathlib
import re
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


_VALID_FEATURE = re.compile(r'^[a-zA-Z0-9_][-a-zA-Z0-9_]*$')
_TEST_COUNT_LIMIT = 1024
_SENTINEL = object()

class Request(typing.NamedTuple):
    """Contents of a "Requests a Run" request."""
    branch: str
    sha: str
    requester: str
    tests: typing.List[str]

    @classmethod
    def from_json_request(cls, request_json: typing.Any) -> 'Request':
        """Validates JSON request and returns a new Request object.

        Checks if all required keys are present and if all of them are of
        correct types.

        Furthermore, validates that --features in test names are correct.  The
        latter is important because anything following --features string in test
        name is included in cargo commands and we don't want to allow arbitrary
        switches to be passed.  The tests are somewhat modified after the
        verification to be in a more of a canonical form.

        Args:
            request_json: The JSON request that user made.
        Returns:
            A new Request object describing the request.
        Raises:
            Failure: if validation fails.
        """
        requester = request_json.get('requester', 'unknown')
        branch = request_json.get('branch', _SENTINEL)
        sha = request_json.get('sha', _SENTINEL)
        tests = request_json.get('tests')

        if branch is _SENTINEL or sha is _SENTINEL:
            raise Failure('Invalid request object: missing branch or sha field')
        if not tests:
            raise Failure('No tests specified')

        if not (isinstance(requester, str) and isinstance(branch, str) and
                isinstance(sha, str) and isinstance(tests, (list, tuple))):
            raise Failure('Invalid request object: '
                          'one of the fields has wrong type')

        return cls(branch=branch, sha=sha, requester=requester,
                   tests=cls._verify_tests(tests))

    @classmethod
    def _verify_tests(cls, tests: typing.List[typing.Any]) -> typing.List[str]:
        """Verifies that requested tests are valid.

        See Request._verify_single_test for description of what it means for
        a single test to be valid.  Apart from checks on individual tests, this
        method also verifies that there was at least one test and no more than
        _TEST_COUNT_LIMIT in the request.  This takes into account that tests
        can be multiplied by having count in front of them.

        Args:
            tests: Tests as given in the JSON request.
        Returns:
            List of tests to schedule.
        Raises:
            Failure: if any of the test is not valid, there are no tests given
                or there are too many tests given.
        """
        result = []
        for test in tests:
            count, test = cls._verify_single_test(test)
            if count + len(result) > _TEST_COUNT_LIMIT:
                raise Failure('Invalid request object: too many tests; '
                              f'max {_TEST_COUNT_LIMIT} allowed')
            result.extend([test] * count)
        if not result:
            raise Failure('Invalid request object: no tests specified')
        return result

    @classmethod
    def _verify_single_test(cls, test: typing.Any) -> typing.Tuple[int, str]:
        """Verifies a single test line.

        Checks that the test is a string and verifies that the --features (if
        any) arguments are correct.  That is, if there's a --features switch in
        the test, everything that follows it must be features and more
        --features switches.  Furthermore, all features must have valid names.

        Note that many things about the test are not checked.  Features are
        checked because they are passed somewhat verbatim to cargo commands and
        we want to control what goes there.  We are less concerned about
        arguments to tests.

        Args:
            test: The test to verify.
        Returns:
            A (count, test) tuple.  The count specifies how many time given test
            should be scheduled and test is the test after some normalisation.
        Raises:
            Failure: if the test is not valid.
        """
        if not isinstance(test, str):
            raise Failure(f'Invalid test: {test}; expected string')
        test = test.strip()
        if not test or test[0] == '#':
            return (0, '')

        words, features = cls._extract_features(test)
        count = int(words.pop(0)) if words and words[0].isnumeric() else 1
        cls._check_test_name(test, words)
        if features:
            words.extend(('--features', ','.join(sorted(features))))
        return count, ' '.join(words)

    @classmethod
    def _extract_features(
            cls, test: str
    ) -> typing.Tuple[typing.Sequence[str], typing.Optional[typing.Set[str]]]:
        """Extracts feature names from test.

        A test can specify features it requires the binaries to be built with.
        For example:

            pytest sanity/proxy_simple.py --features nightly_protocol

        This method extracts those features from test name and the test name
        without the features.

        Args:
            test: The test being parsed.
        Returns:
            A (words, features) tuple where words is the test name sans features
            split into words and features is a set of features present in the
            test (or None if there were no features).  For the aforementioned
            example, the method returns:

                (['pytest', 'sanity/proxy_simple.py'],
                 set(['nightly_protocol']))
        Raises:
            Failure: if the --features have invalid format or any of the
                features have invalid names.
        """
        pos = test.find('--features')
        if pos == -1:
            return test.split(), None

        features = set()
        want_features = False
        for arg in test[pos:].split():
            if want_features:
                features.update(arg.split(','))
                want_features = False
            elif arg == '--features':
                want_features = True
            elif arg.startswith('--features='):
                features.update(arg[11:].split(','))
            else:
                want_features = True
                break
        if want_features:
            raise Failure(f'Invalid features arguments in: {test}')
        for feature in features:
            if not _VALID_FEATURE.search(feature):
                raise Failure(f'Invalid feature "{feature}" in: {test}')
        return test[:pos].split(), features

    @classmethod
    def _check_test_name(cls, test: str, words: typing.Sequence[str]) -> None:
        """Checks whether the test name is valid; raises Failure if not."""
        try:
            idx = 1 + words[1].startswith('--timeout')
            if words[0] in ('pytest', 'mocknet'):
                pattern = r'^[-_a-zA-Z0-9/]+\.py$'
            elif words[0] in ('expensive', 'lib'):
                idx += words[0] == 'expensive'
                pattern = '^[-_a-zA-Z0-9]+$'
            else:
                raise Failure(f'Invalid test category "{words[0]}" in: {test}')
            name = words[idx]
        except ValueError as ex:
            raise Failure(f'Missing test name in: {test}') from ex
        if not re.search(pattern, name):
            raise Failure(f'Invalid test name "{name}" in: {test}')


def _verify_token(server: UIDB,
                  request_json: typing.Dict[str, typing.Any]) -> None:
    """Verifies if request has correct token; raises Failure if not."""
    token = request_json.get('token')
    if token is None:
    #     raise Failure('Your client is too old. NayDuck requires Github auth. '
    #                   'Sync your client to head.')
        return
    github_login = isinstance(token, str) and server.get_github_login(token)
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
    req = Request.from_json_request(request_json)
    with UIDB() as server:
        _verify_token(server, request_json)

        repo_dir = _update_repo()
        sha, user, title = _run(
            'git', 'log', '--format=%H\n%ae\n%s', '-n1', req.sha,
            cwd=repo_dir).decode('utf-8', errors='replace').splitlines()

        builds = {}
        tests = []
        for test in req.tests:
            is_release = '--release' in test
            pos = test.find('--features')
            features = '' if pos < 0 else test[pos:]
            build = builds.setdefault((is_release, features), UIDB.BuildSpec(
                is_release=is_release, features=features))
            build.add_test(has_non_mocknet=not test.startswith('mocknet '))
            test = UIDB.TestSpec(name=test, build=build,
                                 is_remote='--remote' in test)
            tests.append(test)

        # Sort builds by number of dependent tests so that when masters choose
        # what to do they start with builds which unlock the largest number of
        # tests.
        return server.schedule_a_run(
            branch=req.branch, sha=sha, user=user.split('@')[0], title=title,
            builds=sorted(builds.values(), key=lambda build: -build.test_count),
            tests=tests, requester=req.requester)
