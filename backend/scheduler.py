import datetime
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import traceback
import typing

import pytz

from . import backend_db


class Failure(Exception):
    """An exception indicating failure of the request_a_run request."""

    def __init__(self, response: typing.Any) -> None:
        super().__init__(f'Failure. {response}')

    def to_response(self) -> typing.Dict[str, typing.Union[int, str]]:
        """Returns a JSON object intended to return to the caller on failure."""
        return {'code': 1, 'response': self.args[0]}


def _run(*cmd: typing.Union[str, pathlib.Path],
         cwd: typing.Optional[pathlib.Path] = None) -> bytes:
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
        return subprocess.check_output(cmd, cwd=cwd, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as ex:
        command = ' '.join(shlex.quote(str(arg)) for arg in cmd)
        stderr = ex.stderr.decode('utf-8', 'replace')
        raise Failure(f'Command <{command}> terminated with exit code '
                      f'{ex.returncode}:\n{stderr}') from ex


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
    repo_dir = pathlib.Path.home() / 'nearcore.git'

    if repo_dir.is_dir():
        try:
            _run('git', 'remote', 'update', cwd=repo_dir)
            return repo_dir
        except Failure as ex:
            print(ex.args[0], file=sys.stderr)

    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    # Don’t use `clone --mirror` mostly to avoid making `refs/remotes/origin/*`
    # references which (I think) come from GitHub’s internal remotes.  Cloning
    # them gets confusing with `origin/master` not being the expected head of
    # the master branch.
    #
    # There are also `refs/pull/*` references which we’re also skipping.  We
    # probably could include them and offer possibility to run tests on a commit
    # from a pull request. For now, I’m leaving the configuration without that.
    _run('git', 'init', '--bare', repo_dir)
    with open(repo_dir / 'config', 'a', encoding='utf-8') as wr:
        wr.write('''[remote "origin"]
	url = https://github.com/near/nearcore
	fetch = +refs/heads/*:refs/heads/*
	fetch = +refs/notes/*:refs/notes/*
	fetch = +refs/tags/*:refs/tags/*
	tagOpt = --no-tags
	prune = true
''')
    _run('git', 'remote', 'update', cwd=repo_dir)
    return repo_dir


class CommitInfo(typing.NamedTuple):
    sha: str
    title: str

    @classmethod
    def for_commit(cls, repo_dir: pathlib.Path, sha: str) -> 'CommitInfo':
        """Returns commit information for given commit in given repository.

        Args:
            repo_dir: Directory where the repository is located.  Can be
                obtained from _update_repo function.
            sha: A commit reference to retrieve information about.
        Raises:
            Failure: if git command returns an error (most probably because the
                commit does not exist).
        """
        cmd = ('git', 'log', '--format=%H\n%s', '-n1', sha, '--')
        sha, title = _run(*cmd, cwd=repo_dir).decode('utf-8',
                                                     'replace').splitlines()
        return cls(sha=sha, title=cls._shorten_title(title))

    @classmethod
    def _shorten_title(cls, title: str) -> str:
        """Shortens the title if it's longer than 150 characters."""
        if len(title) <= 150:
            return title
        suffix = '…'
        # If title ends with '(#1235)' keep that number at the end
        match = re.search(r'\s*(\(#\d+\))\s*$', title)
        if match:
            suffix = '… ' + match.group(1)
            title = title[:match.start(0)]
        return title[:150 - len(suffix)] + suffix


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
    def from_json(cls, request_json: typing.Any, requester: str) -> 'Request':
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

        return cls(branch=branch,
                   sha=sha,
                   requester=requester,
                   tests=cls.verify_tests(tests))

    def schedule(self,
                 server: backend_db.BackendDB,
                 commit: typing.Optional[CommitInfo] = None) -> int:
        """Saves given run requests to the database.

        Args:
            server: Database connection to use.
            commit: Commit to run the tests on.  If not given, will be
                determined from the repository based on sha given in the
                request.
        Returns:
            Numeric identifier of the scheduled test run.
        Raises:
            Failure: on any kind of error.
        """
        commit = commit or CommitInfo.for_commit(_update_repo(), self.sha)
        builds: typing.Dict[typing.Tuple[bool, str],
                            backend_db.BackendDB.BuildSpec] = {}
        tests: typing.List[backend_db.BackendDB.TestSpec] = []
        for test in self.tests:
            is_release = '--release' in test
            pos = test.find('--features')
            features = '' if pos < 0 else test[pos:]
            build = builds.setdefault(
                (is_release, features),
                backend_db.BackendDB.BuildSpec(is_release=is_release,
                                               features=features))
            build.add_test(has_non_mocknet=not test.startswith('mocknet '))
            tests.append(
                backend_db.BackendDB.TestSpec(name=test,
                                              build=build,
                                              is_remote='--remote' in test))

        # Sort builds by number of dependent tests so that when builders choose
        # what to do they start with builds which unlock the largest number of
        # tests.
        return server.schedule_a_run(branch=self.branch,
                                     sha=commit.sha,
                                     title=commit.title,
                                     requester=self.requester,
                                     tests=tests,
                                     builds=sorted(
                                         builds.values(),
                                         key=lambda build: -build.test_count))

    @classmethod
    def verify_tests(cls,
                     tests: typing.Iterable[typing.Any]) -> typing.List[str]:
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
        result: typing.List[str] = []
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
            cls, test: str) -> typing.Tuple[typing.List[str], typing.Set[str]]:
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
            return test.split(), set()

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
        # ‘adversarial’ is always enabled so remove it from the set if user
        # explicitly enabled it.  If we don’t do that, we may end up doing an
        # unnecessary build.
        features.discard('adversarial')
        for feature in features:
            if not _VALID_FEATURE.search(feature):
                raise Failure(f'Invalid feature "{feature}" in: {test}')
        return test[:pos].split(), features

    @classmethod
    def _check_test_name(cls, test: str, words: typing.List[str]) -> None:
        """Checks whether the test name is valid; raises Failure if not."""
        try:
            idx = 1 + words[1].startswith('--timeout')
            if words[0] in ('pytest', 'mocknet'):
                pattern = r'^[-_a-zA-Z0-9/]+\.py$'
            elif words[0] == 'expensive':
                idx += 1
                pattern = '^[-_a-zA-Z0-9]+$'
            else:
                raise Failure(f'Invalid test category "{words[0]}" in: {test}')
            name = words[idx]
        except ValueError as ex:
            raise Failure(f'Missing test name in: {test}') from ex
        if not re.search(pattern, name):
            raise Failure(f'Invalid test name "{name}" in: {test}')


def schedule_nightly_run() -> datetime.timedelta:
    """Schedules a new nightly run if last one was over 24 hours ago."""
    with backend_db.BackendDB() as server:
        try:
            return _schedule_nightly_impl(server)
        except Exception:
            traceback.print_exc()
            return datetime.timedelta(hours=1)


def _read_tests(repo_dir: pathlib.Path, sha: str) -> typing.List[str]:
    """Reads tests from the repository nightly/nightly.txt file.

    Reads the `nightly/nightly.txt` file in the repository to get the list of
    nightly tests to run.  Verifies all the tests and returns them as a list.
    `./<path>` includes are properly handled.

    The function uses `scripts/nayduck.py` from the repository to perform the
    reading.  Specifically, the `read_tests_from_file` function defined in that
    file.

    The function uses `git show` to read files directly from the git repository
    without checking out the contents of all the files.

    Args:
        repo_dir: Path to the git repository (possibly bare one) to read the
            files from.
        sha: Commit sha to read the files at.
    Returns:
        List of nightly tests to schedule.
    Raises:
        Failure: if any of the test is not valid, there are no tests given or
            there are too many tests given.
    """

    def get_repo_file(filename: str) -> str:
        data = _run('git', 'show', f'{sha}:{filename}', cwd=repo_dir)
        return data.decode('utf-8', 'replace')

    def reader(path: pathlib.Path) -> str:
        filename = os.path.normpath(path)
        if filename.startswith('..') or not filename.endswith('.txt'):
            print(f'Refusing to load tests from {path}', file=sys.stderr)
            return ''
        return get_repo_file(filename)

    mod = {'__file__': 'scripts/nayduck.py'}
    exec(get_repo_file(mod['__file__']), mod)  # pylint: disable=exec-used
    read_tests_from_file = typing.cast(typing.Any, mod['read_tests_from_file'])
    lines = read_tests_from_file(pathlib.Path(mod['DEFAULT_TEST_FILE']),
                                 reader=reader)
    return Request.verify_tests(typing.cast(typing.Iterable[str], lines))


def _schedule_nightly_impl(server: backend_db.BackendDB) -> datetime.timedelta:
    """Implementation of schedule_nightly_run."""
    last = server.last_nightly_run()
    if last:
        now = datetime.datetime.utcnow().replace(tzinfo=pytz.UTC)
        delta = now - last.timestamp
        need_new_run = delta >= datetime.timedelta(hours=24)
        print(f'Last nightly at {last.timestamp}; {delta} ago; sha={last.sha}' +
              ('' if need_new_run else '; no need for a new run'),
              file=sys.stderr)
        if not need_new_run:
            return datetime.timedelta(hours=24) - delta

        repo_dir = _update_repo()
        commit = CommitInfo.for_commit(repo_dir, 'master')
        need_new_run = last.sha != commit.sha
        print(f'master sha={commit.sha}' +
              ('' if need_new_run else '; no need for a new run'),
              file=sys.stderr)
        if not need_new_run:
            return datetime.timedelta(hours=24)

    tests = _read_tests(repo_dir, commit.sha)
    req = Request(branch='master',
                  sha=commit.sha,
                  requester='NayDuck',
                  tests=tests)
    run_id = req.schedule(server, commit)
    print(f'Scheduled new nightly run: /#/run/{run_id}', file=sys.stderr)
    return datetime.timedelta(hours=24)
