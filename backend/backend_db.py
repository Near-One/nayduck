import collections
import datetime
import gzip
import itertools
import time
import typing

from lib import common_db
from lib import testspec

_Row = typing.Any
_Dict = dict[str, typing.Any]
_BuildKey = tuple[bool, str]


def _pop_falsy(dictionary: _Dict, *keys: str) -> None:
    """Remove keys from a dictionary if their values are falsy."""
    for key in keys:
        if not dictionary.get(key, True):
            dictionary.pop(key)


def _update_true(dictionary: _Dict, **kw: typing.Any) -> None:
    for key, value in kw.items():
        if value:
            dictionary[key] = value


class BackendDB(common_db.DB):

    def cancel_the_run(self, run_id: int) -> int:
        """Cancels all the pending tests and builds in the run.

        Builds and tests which are already running are not affected.  Tests are
        put into CANCELED state while builds into BUILD DONE state.

        Args:
            run_id: Run to cancel.
        Returns:
            Number of affected tests and builds.
        """

        def execute() -> int:
            sql = '''UPDATE tests
                        SET finished = NOW(), status = 'CANCELED'
                      WHERE status = 'PENDING' AND run_id = :id'''
            rowcount = int(self._exec(sql, id=run_id).rowcount or 0)
            sql = '''UPDATE builds
                        SET finished = NOW(), status = 'BUILD DONE'
                      WHERE status = 'PENDING' AND run_id = :id'''
            rowcount += int(self._exec(sql, id=run_id).rowcount or 0)
            return rowcount

        return self._in_transaction(execute)

    def retry_the_run(self, run_id: int) -> int:
        """Retry any failed tests in the run.

        Only tests with status FAILED or TIMEOUT are affected.

        Args:
            run_id: Run to cancel.
        Returns:
            Number of affected tests.
        """

        def execute() -> int:
            self._exec('BEGIN ISOLATION LEVEL SERIALIZABLE')
            sql = f'''UPDATE tests
                         SET started = NULL,
                             finished = NULL,
                             status = 'PENDING'
                       WHERE status IN ('FAILED', 'TIMEOUT')
                         AND run_id = {int(run_id)}
                   RETURNING test_id, build_id, skip_build'''
            rows = tuple(self._exec(sql))
            if not rows:
                return 0
            test_ids = ','.join(str(int(row[0])) for row in rows)
            self._exec(f'DELETE FROM logs WHERE test_id IN ({test_ids})')
            build_ids = set(
                str(int(build_id))
                for _, build_id, skip_build in rows
                if not skip_build)
            if build_ids:
                self._exec(f'''UPDATE builds
                                  SET started = NULL,
                                      finished = NULL,
                                      stderr = ''::bytea,
                                      stdout = ''::bytea,
                                      status = 'PENDING'
                                WHERE build_id IN ({','.join(build_ids)})
                                  AND (status = 'BUILD FAILED' OR
                                       (status = 'BUILD DONE' AND
                                        builder_ip = 0))''')
            return len(rows)

        return self._in_transaction(execute)

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
        sql = '''SELECT run_id, branch, encode(sha, 'hex') AS sha, title,
                        requester, timestamp
                   FROM runs
                  ORDER BY run_id DESC
                  LIMIT 100'''
        all_runs = {run['run_id']: run for run in self._fetch_all(sql)}
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

        return sorted(all_runs.values(),
                      key=lambda run: -typing.cast(int, run['run_id']))

    def __get_statuses_for_runs(
            self, min_run_id: int,
            max_run_id: int) -> dict[tuple[int, int], typing.Counter[str]]:
        """Return test statuses for runs with ids in given range.

        Args:
            min_run_id: The lowest run id to return statuses for.
            max_run_id: The highest run id to return statuses for.
        Returns:
            A {(run_id, build_id): {status: count}} dictionary.
        """
        statuses: dict[tuple[int, int],
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
        sql = 'SELECT name, branch FROM tests WHERE test_id = :id LIMIT 1'
        row = self._exec(sql, id=test_id).first()
        if not row:
            return None
        name, branch = row.name, row.branch  # type: ignore
        tests = self.get_full_test_history(name, branch)
        return {
            'name': name,
            'branch': branch,
            'tests': tests,
            'history': self.history_stats(tests),
        }

    def get_full_test_history(self, test_name: str,
                              branch: str) -> typing.Sequence[_Dict]:
        sql = '''SELECT test_id, status, requester, title, status, started,
                        finished, encode(sha, 'hex') AS sha
                   FROM tests JOIN runs USING (run_id)
                  WHERE name = :name
                    AND tests.branch = :branch
                  ORDER BY test_id DESC
                  LIMIT 30'''
        tests = self._fetch_all(sql, name=test_name, branch=branch)
        self._populate_test_logs(tests, blob=False)
        return tests

    def get_test_history(self,
                         test_name: str,
                         branch: str,
                         full: bool = False) -> typing.Sequence[_Dict]:
        sql = '''SELECT test_id, status
                   FROM tests
                  WHERE name = :name
                    AND tests.branch = :branch
                  ORDER BY test_id DESC
                  LIMIT 30'''
        tests = self._fetch_all(sql, name=test_name, branch=branch)
        if full:
            self._populate_test_logs(tests, blob=False)
        return tests

    def get_one_run(
        self, run_id: typing.Union[int, 'BackendDB.LastNightlyRun']
    ) -> typing.Optional[_Dict]:
        if isinstance(run_id, int):
            # NOTE: The set of columns we’re selecting here must be the same as
            # in last_nightly_run method.
            sql = '''SELECT run_id, branch, encode(sha, 'hex') AS sha,
                            timestamp, title, requester
                       FROM runs
                      WHERE run_id = :run_id'''
            run = self._fetch_one(sql, run_id=run_id)
            if not run:
                return None
        else:
            run = self._to_dict(run_id)
            run_id = int(run_id.run_id)

        sql = '''SELECT test_id, status, name, started, finished
                   FROM tests
                  WHERE run_id = :run_id
                  ORDER BY status, started'''
        tests = self._fetch_all(sql, run_id=run_id)
        self._populate_data_about_tests(tests, run['branch'], blob=False)

        run['tests'] = tests
        return run

    def _populate_test_logs(self, tests: typing.Collection[_Dict], *,
                            blob: bool) -> None:
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
        columns = 'test_id, type, size, storage, stack_trace'
        if blob:
            columns += ', log'
        test_ids = ','.join(str(test_id) for test_id in tests_by_id)
        sql = f'''SELECT {columns} FROM logs
                   WHERE test_id IN ({test_ids})
                   ORDER BY test_id, type'''
        for test_id, rows in itertools.groupby(
                self._exec(sql), lambda row: typing.cast(int, row.test_id)):
            tests_by_id[test_id]['logs'] = [process_log(row) for row in rows]

    def _populate_data_about_tests(self, tests: typing.Collection[_Dict],
                                   branch: str, *, blob: bool) -> None:
        self._populate_test_logs(tests, blob=blob)
        for test in tests:
            history = self.get_test_history(test['name'], branch)
            test['history'] = self.history_stats(history)

    def get_build_info(self, build_id: int) -> typing.Optional[_Dict]:
        sql = '''SELECT run_id, status, started, finished, stderr, stdout,
                        features, is_release, branch, encode(sha, 'hex') AS sha,
                        title, requester
                   FROM builds JOIN runs USING (run_id)
                  WHERE build_id = :id
                  LIMIT 1'''
        build = self._fetch_one(sql, id=build_id)
        if build:
            build['stdout'] = self._str_from_blob(build['stdout'])
            build['stderr'] = self._str_from_blob(build['stderr'])
            _pop_falsy(build, 'stdout', 'stderr')
        return build

    def get_history_for_branch(self, test_id: int,
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
        sql = '''SELECT test_id, run_id, build_id, status, name, timeout,
                        skip_build, started, finished, runs.branch, tries,
                        ENCODE(sha, 'hex') AS sha, title, requester, worker_hostname, is_nightly
                   FROM tests JOIN runs USING (run_id)
                  WHERE test_id = :id
                  LIMIT 1'''
        test = self._fetch_one(sql, id=test_id)
        if not test:
            return None

        success_status = ('PASSED', 'IGNORED', 'RUNNING', 'PENDING')
        if test['is_nightly'] and test['status'] not in success_status:
            # We’re explicitly filtering on branch so that we can reuse an existing
            # index which has branch as first key.
            sql = '''SELECT ENCODE(sha, 'hex') AS sha, status
                       FROM tests JOIN runs USING (run_id)
                      WHERE tests.branch = 'master'
                        AND name = :name
                        AND test_id < :id
                        AND status NOT in ('RUNNING', 'PENDING')
                        AND is_nightly
                      ORDER BY test_id DESC LIMIT 30'''
            first_bad = test['sha']
            last_good = None
            for row in self._exec(sql, name=test['name'], id=test['test_id']):
                if row.status in success_status:
                    last_good = row.sha
                    break
                first_bad = row.sha
            if first_bad and last_good:
                test['first_bad'] = first_bad
                test['last_good'] = last_good

        self._populate_data_about_tests([test], test['branch'], blob=True)
        return test

    def schedule_a_run(self, *, branch: str, sha: str, title: str,
                       tests: typing.Iterable[testspec.TestSpec],
                       requester: str) -> int:
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
            tests: A sequence of tests to schedule.
            requester: User who requested the tests.
        Returns:
            Id of the scheduled run.
        """
        builds = collections.defaultdict(list)
        for test in tests:
            builds[(test.is_release, test.features)].append(test)
        return self._in_transaction(self.__do_schedule,
                                    branch=branch,
                                    sha=sha,
                                    title=title,
                                    builds=builds,
                                    requester=requester)

    def __do_schedule(self, *, branch: str, sha: str, title: str,
                      builds: typing.Mapping[_BuildKey,
                                             testspec.TestSpecSequence],
                      requester: str) -> int:
        """Implementation for schedule_a_run executed in a transaction."""
        is_nightly = requester == 'NayDuck'

        # Into Runs
        run_id = self._insert('runs',
                              'run_id',
                              branch=branch,
                              sha=bytes.fromhex(sha),
                              title=title,
                              requester=requester)

        # Into Builds
        def builds_row(
            item: tuple[_BuildKey, testspec.TestSpecSequence]
        ) -> tuple[int, str, bool, str, bool]:
            (is_release, features), tests = item
            skip_build = all(test.skip_build for test in tests)
            status = 'BUILD DONE' if skip_build else 'PENDING'
            return (run_id, status, is_release, features, is_nightly)

        build_items = sorted(builds.items(), key=lambda item: -len(item[1]))
        rows = self._multi_insert(
            'builds',
            ('run_id', 'status', 'is_release', 'features', 'low_priority'),
            [builds_row(itm) for itm in build_items],
            returning=('build_id', 'is_release', 'features'))

        # Into Tests
        columns = ('run_id', 'build_id', 'name', 'category', 'timeout',
                   'skip_build', 'branch', 'is_nightly')
        new_rows = sorted((run_id, build_id, test.short_name, test.category,
                           test.timeout, test.skip_build, branch, is_nightly)
                          for build_id, is_release, features in rows
                          for test in builds[(is_release, features)])
        self._multi_insert('tests', columns, new_rows)

        return run_id

    def get_tests_by_status(self, status) -> typing.Optional[_Dict]:
        sql = '''SELECT test_id, status, name, started, timeout
                   FROM tests
                  WHERE status = :status
                  ORDER BY status'''
        tests = self._fetch_all(sql, status=status)

        return tests

    def clear_stale_tests(self, test_ids) -> int:
        """Clears RUNNING tests status for given test_ids
        Args:
            test_ids: List of test_id's.
        Returns:
            Number of affected tests.
        """

        def execute() -> int:
            sql = '''UPDATE tests
                        SET status = 'PENDING',
                            tries = tries - 1
                      WHERE test_id IN :ids
                        AND status = 'RUNNING'
                      '''

            rowcount = int(self._exec(sql, ids=tuple(test_ids)).rowcount or 0)
            return rowcount

        return self._in_transaction(execute)

    class LastNightlyRun:
        run_id: int
        branch: str
        sha: str
        timestamp: datetime.datetime
        title: str
        requester: str

    def last_nightly_run(self) -> typing.Optional['BackendDB.LastNightlyRun']:
        """Returns the last nightly run."""
        # NOTE: The set of columns we’re selecting here must be the same as
        # in get_one_run method.
        row = self._exec('''SELECT run_id, branch, encode(sha, 'hex') AS sha,
                                   timestamp, title, requester
                              FROM runs
                             WHERE requester = 'NayDuck'
                             ORDER BY timestamp DESC
                             LIMIT 1''').first()
        return typing.cast(typing.Optional[BackendDB.LastNightlyRun], row)

    class NayDuckMetrics(typing.NamedTuple):
        run_id: int
        start: datetime.datetime
        finish: typing.Optional[datetime.datetime]
        test_statuses: typing.Sequence[typing.Sequence[typing.Any]]
        test_keys: typing.Sequence[str]
        build_statuses: list[typing.Sequence[typing.Any]]
        build_keys: typing.Sequence[str]
        last_test_success: typing.Mapping[str, float]

    def get_metrics(self) -> typing.Optional['BackendDB.NayDuckMetrics']:
        """Returns metrics to export via Prometheus metrics reporting."""
        nightly = self.last_nightly_run()
        if not nightly:
            return None

        run_id = int(nightly.run_id)
        tests = list(
            self._exec(f'''SELECT test_id, name, status, finished
                             FROM tests
                            WHERE run_id = {run_id}'''))
        test_keys = ('test_id', 'name', 'status')
        builds = list(
            self._exec(f'''SELECT build_id, features, status
                             FROM builds
                            WHERE run_id = {run_id}'''))
        build_keys = ('build_id', 'features', 'status')

        max_finished: typing.Optional[datetime.datetime] = None
        finished = None
        for test in tests:
            if not test.finished:
                break
            if max_finished:
                max_finished = max(max_finished, test.finished)
            else:
                max_finished = test.finished
        else:
            finished = max_finished

        last_test_success = {}
        now = datetime.datetime.utcnow()
        for test in tests:
            timestamp: typing.Optional[datetime.datetime] = now
            if test.status not in ('PASSED', 'IGNORED'):
                timestamp = self.__get_last_test_success(test.name, now)
            if timestamp:
                last_test_success[test.name] = timestamp.timestamp()

        return self.NayDuckMetrics(run_id=run_id,
                                   start=nightly.timestamp,
                                   finish=finished,
                                   test_statuses=tests,
                                   test_keys=test_keys,
                                   build_statuses=builds,
                                   build_keys=build_keys,
                                   last_test_success=last_test_success)

    class NightlyTestEvent:
        timestamp: datetime.datetime
        run_id: int
        name: str
        status: str

    def get_nightly_events(
            self) -> typing.Sequence['BackendDB.NightlyTestEvent']:
        """Returns nightly runs events."""
        rows = self._exec('''
            SELECT timestamp, run_id, name, status
              FROM runs JOIN tests USING (run_id)
             WHERE requester = 'NayDuck'
               AND timestamp >= CURRENT_TIMESTAMP - interval '91 days'
               AND finished IS NOT NULL
             ORDER BY timestamp
        ''')
        return typing.cast(typing.Sequence[BackendDB.NightlyTestEvent],
                           list(rows))

    def __get_last_test_success(
            self, name: str,
            now: datetime.datetime) -> typing.Optional[datetime.datetime]:
        """Returns timestamp when the test was last known to be successful.

        Looks at 30 most recent finished nightly runs of test with given `name`.
        If the most recent run was passing (i.e. in state PASSED or IGNORED)
        returns `now`.  Otherwise, scans test runs backwards looking for the
        first failed test which started current failed runs sequence and returns
        its finished timestamp.

        Args:
            name: Name of the test to investigate.
            now: ‘Now’ timestamp.
        Returns:
            None if the test did not finish any nightly runs yet otherwise
            highest timestamp when it looked like it was passing.
        """
        sql = '''SELECT status, finished
                   FROM tests
                  WHERE name = :name
                    AND is_nightly
                    AND finished IS NOT NULL
                    AND status NOT IN ('PENDING', 'RUNNING')
                  ORDER BY finished DESC
                  LIMIT 30'''
        timestamp = None
        for status, finished in self._exec(sql, name=name):
            if timestamp is None:
                timestamp = now
            if status in ('PASSED', 'IGNORED'):
                break
            timestamp = finished
        return timestamp

    def add_auth_cookie(self, timestamp: int, cookie: int) -> None:
        """Adds an authentication cookie to the database.

        While at it also deletes all expired cookies.

        Authentication cookies are used in the GitHub authentication flow.  When
        user logs in we generate a cookie and send it as state with a request to
        GitHub.  GitHub than sends it back to us so we can verify that the
        request came from us and is valid.

        Args:
            timestamp: Time when the cookie was generated as a 32-bit integer
                timestamp.  This is also interpreted as ‘now’, i.e. the method
                decides which cookies have expired based on this value.
            cookie: A 64-bit integer cookie to add to the database.
        """
        self._exec('DELETE FROM auth_cookies WHERE timestamp < :ts',
                   ts=timestamp - 600)
        self._insert('auth_cookies', timestamp=timestamp, cookie=cookie)

    def verify_auth_cookie(self, timestamp: int, cookie: int) -> bool:
        """Verifies that an authentication cookie exists in the database.

        The cookie (as well as all expired cookies) are removed from the
        database so subsequent calls to this method will return False for the
        same cookie.

        Authentication cookies are used in the GitHub authentication flow.  When
        user logs in we generate a cookie and send it as state with a request to
        GitHub.  GitHub than sends it back to us so we can verify that the
        request came from us and is valid.

        Args:
            timestamp: Timestamp when the cookie was generated as a 32-bit
                integer timestamp.
            cookie: A 64-bit integer cookie to add to the database.
        Returns:
            Whether the cookie existed in the database.
        """
        sql = '''DELETE FROM auth_cookies
                  WHERE timestamp = :ts AND cookie = :cookie'''
        found = bool(self._exec(sql, ts=timestamp, cookie=cookie).rowcount)
        self._exec('DELETE FROM auth_cookies WHERE timestamp < :tm',
                   tm=int(time.time()) - 600)
        return found

    def get_test_log(
        self, test_id: int, log_type: str, gzip_ok: bool
    ) -> tuple[bytes, typing.Optional[datetime.datetime], bool]:
        """Returns given test log.

        Args:
            test_id: Test id to return log for.
            log_type: Name of the log to return.
            gzip_ok: If True and the log is stored compressed in the database
                returns the log as such.  If False will always return
                decompressed log.
        Returns:
            A (contents, ctime, is_compressed) tuple where the first element is
            contents of the log, second is time the file was created and third
            says whether the contents is compressed or not.  Third element is
            always False if gzip_ok argument is False.
        Raises:
            KeyError: if given log does not exist.
        """
        sql = '''SELECT finished, log
                   FROM logs JOIN tests USING (test_id)
                  WHERE test_id = :id AND type = :tp
                  LIMIT 1'''
        return self._get_log_impl(sql, id=test_id, tp=log_type, gzip_ok=gzip_ok)

    def get_build_log(
        self, build_id: int, log_type: str, gzip_ok: bool
    ) -> tuple[bytes, typing.Optional[datetime.datetime], bool]:
        """Returns given build log.

        Args:
            build_id: Build id to return log for.
            log_type: Name of the log to return.  Can be either 'stderr' or
                'stdout'.
            gzip_ok: If True and the log is stored compressed in the database
                returns the log as such.  If False will always return
                decompressed log.
        Returns:
            A (contents, ctime, is_compressed) tuple where the first element is
            contents of the log, second is time the file was created and third
            says whether the contents is compressed or not.  Third element is
            always False if gzip_ok argument is False.
        Raises:
            KeyError: if given log does not exist.
            AssertionError: if log_type is not 'stderr' or 'stdout'.
        """
        assert log_type in ('stderr', 'stdout')
        sql = f'SELECT finished, {log_type} FROM builds WHERE build_id = :id'
        return self._get_log_impl(sql, id=build_id, gzip_ok=gzip_ok)

    def _get_log_impl(
        self, sql: str, gzip_ok: bool, **kw: typing.Any
    ) -> tuple[bytes, typing.Optional[datetime.datetime], bool]:
        """Returns a log from the database.

        Args:
            sql: The SQL query to execute to fetch the log.  The query must
                return at most one with two columns.  First column is
                a timestamp the log was created and the second is the log
                contents.
            gzip_ok: If True and the log is stored compressed in the database
                returns the log as such.  If False will always return
                decompressed log.
            kw: Arguments to use in placeholders of the query.
        Returns:
            A (contents, ctime, is_compressed).
        Raises:
            KeyError: if given SQL query returned no rows.
        """
        row = self._exec(sql, **kw).first()
        if not row:
            raise KeyError()
        ctime, blob = row
        is_compressed = bytes(blob[:2]) == b'\x1f\x8b'
        if is_compressed and not gzip_ok:
            blob = gzip.decompress(blob)
            is_compressed = False
        else:
            blob = bytes(blob)
        return blob, ctime, is_compressed

    def get_system_stats(self) -> _Dict:
        """Returns statistics such us number of running builds and tests."""
        sql = '''SELECT status, COUNT(*)
                   FROM builds
                  WHERE status IN ('PENDING', 'BUILDING')
                  GROUP BY 1'''
        build_stats = dict(
            (status.lower(), count) for status, count in self._exec(sql))
        sql = '''SELECT status, COUNT(*)
                   FROM tests
                  WHERE status IN ('PENDING', 'RUNNING')
                  GROUP BY 1'''
        test_stats = dict(
            (status.lower(), count) for status, count in self._exec(sql))
        return {'build': build_stats, 'test': test_stats}
