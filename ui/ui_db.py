import collections
import datetime
import gzip
import itertools
import typing

from lib import common_db

_Row = typing.Any
_Dict = typing.Dict[str, typing.Any]


def _pop_falsy(dictionary: _Dict, *keys: str) -> None:
    """Remove keys from a dictionary if their values are falsy."""
    for key in keys:
        if not dictionary.get(key, True):
            dictionary.pop(key)


def _update_true(dictionary: _Dict, **kw: typing.Any) -> None:
    for key, value in kw.items():
        if value:
            dictionary[key] = value


class UIDB(common_db.DB):

    def cancel_the_run(self, run_id: int, status: str = 'CANCELED') -> None:
        sql = '''UPDATE tests
                    SET finished = NOW(), status = :status
                  WHERE status = 'PENDING' AND run_id = :id'''
        self._exec(sql, status=status, id=run_id)

    _STATUS_CATEGORIES = ('pending', 'running', 'passed', 'ignored',
                          'build_failed', 'canceled', 'timeout')
    _NO_STATUSES = dict.fromkeys(_STATUS_CATEGORIES + ('failed',), 0)
    _NO_BUILDS = ({
        'build_id': 0,
        'status': 'TEST SPECIFIC',
        'is_release': False,
        'features': '',
        'tests': _NO_STATUSES,
    },)

    def get_all_runs(self) -> typing.Iterable[_Dict]:
        # Get the last 100 runs
        sql = '''SELECT id, branch, sha, title, requester, timestamp
                   FROM runs
                  ORDER BY id DESC
                  LIMIT 100'''
        all_runs = {run['id']: run for run in self._fetch_all(sql)}
        min_id, max_id = min(all_runs), max(all_runs)

        statuses = self.__get_statuses_for_runs(min_id, max_id)

        # Get builds for the last 100 runs.
        sql = '''SELECT run_id, build_id, status, is_release, features
                   FROM builds
                  WHERE run_id BETWEEN :lo AND :hi'''
        result = self._exec(sql, lo=min_id, hi=max_id)
        for run_id, build_id, status, is_release, features in result:
            build = {
                'build_id': build_id,
                'status': status,
                'tests': statuses.get((run_id, build_id), self._NO_STATUSES)
            }
            _update_true(build, is_release=is_release, features=features)
            all_runs[run_id].setdefault('builds', []).append(build)

        # Fill out fake builds for any old runs which don't have corresponding
        # builds.  In practice this is never executed since those runs no longer
        # show up on the dashboard in the top 100.
        for run in all_runs.values():
            run.setdefault('builds', self._NO_BUILDS)

        return sorted(all_runs.values(),
                      key=lambda run: -typing.cast(int, run['id']))

    def __get_statuses_for_runs(
        self, min_run_id: int, max_run_id: int
    ) -> typing.Dict[typing.Tuple[int, int], typing.Counter[str]]:
        """Return test statuses for runs with ids in given range.

        Args:
            min_run_id: The lowest run id to return statuses for.
            max_run_id: The highest run id to return statuses for.
        Returns:
            A {(run_id, build_id): {status: count}} dictionary.
        """
        statuses: typing.Dict[typing.Tuple[int, int],
                              typing.Counter[str]] = collections.defaultdict(
                                  collections.Counter)
        sql = '''SELECT run_id, build_id, status, COUNT(status)
                   FROM tests
                  WHERE run_id BETWEEN :lo AND :hi
                  GROUP BY 1, 2, 3'''
        result = self._exec(sql, lo=min_run_id, hi=max_run_id)
        for run_id, build_id, status, count in result:
            counter = statuses[(run_id, build_id or 0)]
            status = status.lower().replace(' ', '_')
            if status in self._STATUS_CATEGORIES:
                counter[status.lower().replace(' ', '_')] += count
            if 'failed' in status:
                counter['failed'] += count
        return statuses

    def get_test_history_by_id(self, test_id: int) -> typing.Optional[_Dict]:
        sql = '''SELECT t.name, r.branch
                   FROM tests AS t, runs AS r
                  WHERE t.test_id = :id AND r.id = t.run_id
                  LIMIT 1'''
        row = self._exec(sql, id=test_id).first()
        if not row:
            return None
        tests = self.get_test_history(row.name,
                                      row.branch,
                                      interested_in_logs=True)
        return {
            'branch': row.branch,
            'tests': tests,
            'history': self.history_stats(tests),
        }

    def get_test_history(
            self,
            test_name: str,
            branch: str,
            interested_in_logs: bool = False) -> typing.Sequence[_Dict]:
        sql = '''SELECT t.test_id, r.requester, r.title, t.status, t.started,
                        t.finished, r.branch, r.sha
                   FROM tests AS t, runs AS r
                  WHERE name = :name AND t.run_id = r.id AND r.branch = :branch
                  ORDER BY t.test_id DESC
                  LIMIT 30'''
        tests = self._fetch_all(sql, name=test_name, branch=branch)
        if interested_in_logs:
            self._populate_test_logs(tests, blob=False)
        return tests

    def get_one_run(self, run_id: int) -> typing.Sequence[_Dict]:
        sql = '''SELECT test_id, status, name, started, finished, branch
                   FROM tests JOIN runs ON (runs.id = tests.run_id)
                  WHERE run_id = :id
                  ORDER BY status, started'''
        tests = self._fetch_all(sql, id=run_id)
        if tests:
            branch = tests[0]['branch']
            for test in tests:
                test.pop('branch')
            self._populate_data_about_tests(tests, branch, blob=False)
        return tests

    def _populate_test_logs(self,
                            tests: typing.Collection[_Dict],
                            blob: bool = False) -> None:
        if not tests:
            return

        def process_log(log: _Row) -> _Dict:
            ret = self._to_dict(log)
            ret.pop('test_id')
            if blob:
                data = None
                if not ret['type'].endswith('.gz'):
                    data = self._str_from_blob(ret['log'])
                if data:
                    ret['log'] = data
                else:
                    ret.pop('log')
            return ret

        tests_by_id = {int(test['test_id']): test for test in tests}
        sql = '''SELECT test_id, type, size, storage, stack_trace, patterns
                        {log_column}
                   FROM logs
                  WHERE test_id IN ({ids})
                  ORDER BY test_id, type'''.format(
            log_column=', log' if blob else '',
            ids=','.join(str(test_id) for test_id in tests_by_id))
        for test_id, rows in itertools.groupby(
                self._exec(sql), lambda row: typing.cast(int, row.test_id)):
            tests_by_id[test_id]['logs'] = [process_log(row) for row in rows]

    def _populate_data_about_tests(self,
                                   tests: typing.Collection[_Dict],
                                   branch: str,
                                   blob: bool = False) -> None:
        self._populate_test_logs(tests, blob=blob)
        for test in tests:
            history = self.get_test_history(test['name'], branch)
            test['history'] = self.history_stats(history)

    def get_build_info(self, build_id: int) -> typing.Optional[_Dict]:
        sql = '''SELECT run_id, status, started, finished, stderr, stdout,
                        features, is_release, branch, sha, title, requester
                   FROM builds JOIN runs ON (runs.id = builds.run_id)
                  WHERE build_id = :id
                  LIMIT 1'''
        build = self._fetch_one(sql, id=build_id)
        if build:
            build['stdout'] = self._str_from_blob(build['stdout'])
            build['stderr'] = self._str_from_blob(build['stderr'])
            _pop_falsy(build, 'stdout', 'stderr')
        return build

    def get_histoty_for_base_branch(self, test_id: int,
                                    branch: str) -> typing.Optional[_Row]:
        sql = 'SELECT name FROM tests WHERE test_id = :id LIMIT 1'
        test = self._fetch_one(sql, id=test_id)
        if not test:
            return None
        history = self.get_test_history(test['name'], branch)
        if history:
            test_id_base_branch = history[0]['test_id']
        else:
            test_id_base_branch = -1
        return {
            'history': self.history_stats(history),
            'test_id': test_id_base_branch
        }

    @classmethod
    def history_stats(cls,
                      history: typing.Sequence[_Dict]) -> typing.Sequence[int]:
        # passed, other, failed
        res = [0, 0, 0]
        for hist in history:
            if hist['status'] == 'PASSED':
                res[0] += 1
            elif hist['status'] in ('FAILED', 'BUILD FAILED', 'TIMEOUT'):
                res[2] += 1
            else:
                res[1] += 1
        return res

    def get_one_test(self, test_id: int) -> typing.Optional[_Dict]:
        sql = '''SELECT test_id, run_id, build_id, status, name, started,
                        finished, branch, sha, title, requester
                   FROM tests JOIN runs ON (runs.id = tests.run_id)
                  WHERE test_id = :id
                  LIMIT 1'''
        test = self._fetch_one(sql, id=test_id)
        if test:
            self._populate_data_about_tests([test], test['branch'], blob=True)
        return test

    class BuildSpec:
        """Specification for a build.

        Attributes:
            is_release: Whether the build should use release build profile.
            features: Features command line arguments to use when building.
            has_non_mocknet: Whether any non-mocknet test depends on this build.
                At the moment, mocknet tests don't need a build so a build with
                no non-mocknet tests becomes a no-op.
            build_id: A build_id filled in by UIDB.schedule_a_run when the build
                is inserted into the database.
            test_count: Number of tests depending on this build.
        """

        def __init__(self, *, is_release: bool, features: str) -> None:
            self.is_release = is_release
            self.features = features
            self.has_non_mocknet = False
            self.build_id = 0
            self.test_count = 0

        def add_test(self, *, has_non_mocknet: bool) -> None:
            self.has_non_mocknet = self.has_non_mocknet or has_non_mocknet
            self.test_count += 1

    class TestSpec:
        """Specification for a test.

        Attributes:
            name: Name of the tests which also describes the command to be
                executed.
            is_remote: Whether the test is remote.
            build: A BuildSpec this test depends on.  This is used to get the
                build_id.
        """

        def __init__(self, *, name: str, is_remote: bool,
                     build: 'UIDB.BuildSpec') -> None:
            self.name = name
            self.is_release = build.is_release
            self.is_remote = is_remote
            self.build = build

        category = property(lambda self: self.name.split()[0])

    def schedule_a_run(self, *, branch: str, sha: str, title: str,
                       builds: typing.Sequence['UIDB.BuildSpec'],
                       tests: typing.Sequence['UIDB.TestSpec'], requester: str,
                       is_nightly: bool) -> int:
        """Schedules a run with given set of pending tests to the database.

        Adds a run comprising of all specified tests as well as all builds the
        tests depend on.

        Args:
            branch: Branch name on which the tests are run.  This is really only
                informative and in practice can be any string but nominally this
                should be the branch name which contains commit the build is
                for.
            sha: Commit sha to run the tests on.
            title: Subject of the commit.
            builds: A sequence of builds necessary for the tests to run.  The
                builds are modified in place by having their build_id set.
            tests: A sequence of tests to add as a sequence of TestSpec objects.
            requester: User who requested the tests.
            is_nightly: Whether this request is a nightly run requests.  It will
                be marked as such in the database so that the scheduler can
                figure out when was the last nightly run.  Furthermore, nightly
                runs are run with lower priority.
        Returns:
            Id of the scheduled run.
        """
        return self._in_transaction(self.__do_schedule,
                                    branch=branch,
                                    sha=sha,
                                    title=title,
                                    builds=builds,
                                    tests=tests,
                                    requester=requester,
                                    is_nightly=is_nightly)

    def __do_schedule(self, *, branch: str, sha: str, title: str,
                      builds: typing.Sequence['UIDB.BuildSpec'],
                      tests: typing.Sequence['UIDB.TestSpec'], requester: str,
                      is_nightly: bool) -> int:
        """Implementation for schedule_a_run executed in a transaction."""
        # Into Runs
        run_id = self._insert('runs',
                              branch=branch,
                              sha=sha,
                              title=title,
                              requester=requester,
                              is_nightly=is_nightly)

        # Into Builds
        for build in builds:
            build_status = 'PENDING' if build.has_non_mocknet else 'SKIPPED'
            build.build_id = self._insert('builds',
                                          run_id=run_id,
                                          status=build_status,
                                          features=build.features,
                                          is_release=build.is_release,
                                          priority=int(is_nightly))

        # Into Tests
        columns = ('run_id', 'build_id', 'name', 'category', 'priority',
                   'remote')
        self._multi_insert('tests', columns,
                           [(run_id, test.build.build_id, test.name,
                             test.category, int(is_nightly), test.is_remote)
                            for test in tests])

        return run_id

    class LastNightlyRun:
        timestamp: datetime.datetime
        sha: str

    def last_nightly_run(self) -> typing.Optional['UIDB.LastNightlyRun']:
        """Returns the last nightly run."""
        row = self._exec('''SELECT timestamp, sha
                              FROM runs
                             WHERE is_nightly
                             ORDER BY timestamp DESC
                             LIMIT 1''').first()
        return typing.cast(typing.Optional[UIDB.LastNightlyRun], row)

    def add_auth_nonce(self, nonce: bytes, now: int) -> None:
        """Adds an authentication nonce to the database.

        While at it also deletes all expired nonces.

        Args:
            nonce: A 12-byte nonce to add to the database.
            now: Time when the nonce was generated.
        """
        self._exec('DELETE FROM auth_codes WHERE timestamp < :tm', tm=now - 600)
        self._insert('auth_codes', nonce=nonce, timestamp=now)

    def verify_auth_nonce(self, nonce: bytes, now: int) -> bool:
        """Verifies that an authentication nonce exists in the database.

        The nonce (as well as all expired nonces) are removed from the database
        so subsequent calls to this method will return False for the same nonce.

        Args:
            nonce: Nonce to verify existence of.
            now: Current timestamp.
        Returns:
            Whether the nonce existed in the database.
        """
        sql = 'DELETE FROM auth_codes WHERE nonce = :nonce'
        found = bool(self._exec(sql, nonce=nonce).rowcount)
        self._exec('DELETE FROM auth_codes WHERE timestamp < :tm', tm=now - 600)
        return found

    def get_test_log(self, test_id: int, log_type: str,
                     gzip_ok: bool) -> typing.Tuple[bytes, bool]:
        """Returns given test log.

        Args:
            test_id: Test id to return log for.
            log_type: Name of the log to return.
            gzip_ok: If True and the log is stored compressed in the database
                returns the log as such.  If False will always return
                decompressed log.
        Returns:
            A (contents, is_compressed) tuple where the first element is
            contents of the log and second says whether the contents is
            compressed or not.  Second element is always False if gzip_ok
            argument is False.
        Raises:
            KeyError: if given log does not exist.
        """
        sql = 'SELECT log FROM logs WHERE test_id = :id AND type = :tp LIMIT 1'
        return self._get_log_impl(sql, id=test_id, tp=log_type, gzip_ok=gzip_ok)

    def get_build_log(self, build_id: int, log_type: str,
                      gzip_ok: bool) -> typing.Tuple[bytes, bool]:
        """Returns given build log.

        Args:
            build_id: Build id to return log for.
            log_type: Name of the log to return.  Can be either 'stderr' or
                'stdout'.
            gzip_ok: If True and the log is stored compressed in the database
                returns the log as such.  If False will always return
                decompressed log.
        Returns:
            A (contents, is_compressed) tuple where the first element is
            contents of the log and second says whether the contents is
            compressed or not.  Second element is always False if gzip_ok
            argument is False.
        Raises:
            KeyError: if given log does not exist.
            AssertionError: if log_type is not 'stderr' or 'stdout'.
        """
        assert log_type in ('stderr', 'stdout')
        sql = f'SELECT {log_type} FROM builds WHERE build_id = :id LIMIT 1'
        return self._get_log_impl(sql, id=build_id, gzip_ok=gzip_ok)

    def _get_log_impl(self, sql: str, gzip_ok: bool,
                      **kw: typing.Any) -> typing.Tuple[bytes, bool]:
        """Returns a log from the database.

        Args:
            sql: The SQL query to execute to fetch the log.  The query should
                return one row with a single column whose value is the log
                contents.
            gzip_ok: If True and the log is stored compressed in the database
                returns the log as such.  If False will always return
                decompressed log.
            kw: Arguments to use in placeholders of the query.
        Returns:
            A (contents, is_compressed) tuple where the first element is
            contents of the log and second says whether the contents is
            compressed or not.  Second element is always False if gzip_ok
            argument is False.
        Raises:
            KeyError: if given SQL query returned no rows.
        """
        row = self._exec(sql, **kw).first()
        if not row:
            raise KeyError()
        blob = row[0]
        is_compressed = bytes(blob[:2]) == b'\x1f\x8b'
        if is_compressed and not gzip_ok:
            blob = gzip.decompress(blob)
            is_compressed = False
        return blob, is_compressed
