import collections
import itertools
import os
import random
import string
import sys
import typing

sys.path.append(os.path.abspath('../main_db'))
import common_db  # pylint: disable=wrong-import-position


def _pop_falsy(dictionary, *keys):
    """Remove keys from a dictionary if their values are falsy."""
    for key in keys:
        if not dictionary.get(key, True):
            dictionary.pop(key)


class UIDB(common_db.DB):

    def cancel_the_run(self, run_id, status='CANCELED'):
        sql = '''UPDATE tests
                    SET finished = NOW(), status = %s
                  WHERE status = 'PENDING' AND run_id = %s'''
        self._exec(sql, status, run_id)

    def get_auth_code(self, login):
        sql = 'SELECT code FROM users WHERE name = %s LIMIT 1'
        result = self._exec(sql, login)
        user = result.fetchone()
        if user:
            code = user['code']
        else:
            alphabet = string.ascii_uppercase + string.digits
            code = ''.join(random.choices(alphabet, k=20))
            self._insert('users', name=login, code=code)
        return code

    def get_github_login(self, token):
        sql = 'SELECT name FROM users WHERE code = %s LIMIT 1'
        result = self._exec(sql, token)
        login = result.fetchone()
        if login:
            return login['name']
        return None

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

    def get_all_runs(self):
        # Get the last 100 runs
        sql = '''SELECT id, branch, sha, title, requester
                   FROM runs
                  ORDER BY id DESC
                  LIMIT 100'''
        all_runs = dict(
            (int(run['id']), run) for run in self._exec(sql).fetchall())
        run_id_range = min(all_runs), max(all_runs)

        statuses = self.__get_statuses_for_runs(*run_id_range)

        # Get builds for the last 100 runs.
        sql = '''SELECT run_id, build_id, status, is_release, features
                   FROM builds
                  WHERE run_id BETWEEN %s AND %s'''
        for build in self._exec(sql, *run_id_range).fetchall():
            run_id = int(build.pop('run_id'))
            build_id = int(build['build_id'])
            build['tests'] = statuses.get((run_id, build_id), self._NO_STATUSES)
            _pop_falsy(build, 'is_release', 'features')
            all_runs[run_id].setdefault('builds', []).append(build)

        # Fill out fake builds for any old runs which don't have corresponding
        # builds.  In practice this is never executed since those runs no longer
        # show up on the dashboard in the top 100.
        for run in all_runs.values():
            run.setdefault('builds', self._NO_BUILDS)

        return sorted(all_runs.values(), key=lambda run: -run['id'])

    def __get_statuses_for_runs(self, min_run_id: int, max_run_id: int):
        """Return test statuses for runs with ids in given range.

        Args:
            min_run_id: The lowest run id to return statuses for.
            max_run_id: The highest run id to return statuses for.
        Returns:
            A {(run_id, build_id): {status: count}} dictionary.
        """
        statuses = collections.defaultdict(collections.Counter)
        sql = '''SELECT run_id, build_id, status, COUNT(status) AS cnt
                   FROM tests
                  WHERE run_id BETWEEN %s AND %s
                  GROUP BY 1, 2, 3'''
        result = self._exec(sql, min_run_id, max_run_id)
        for test in result.fetchall():
            counter = statuses[(int(test['run_id']), int(test['build_id'] or
                                                         0))]
            status = test['status'].lower().replace(' ', '_')
            if status in self._STATUS_CATEGORIES:
                counter[status.lower().replace(' ', '_')] += int(test['cnt'])
            if 'failed' in status:
                counter['failed'] += int(test['cnt'])
        return statuses

    def get_test_history_by_id(self, test_id):
        sql = '''SELECT t.name, r.branch
                   FROM tests AS t, runs AS r
                  WHERE t.test_id = %s AND r.id = t.run_id
                  LIMIT 1'''
        row = self._exec(sql, test_id).fetchone()
        if not row:
            return None
        tests = self.get_test_history(row['name'],
                                      row['branch'],
                                      interested_in_logs=True)
        return {
            'branch': row['branch'],
            'tests': tests,
            'history': self.history_stats(tests),
        }

    def get_test_history(self, test_name, branch, interested_in_logs=False):
        sql = '''SELECT t.test_id, r.requester, r.title, t.status, t.started,
                        t.finished, r.branch, r.sha
                   FROM tests AS t, runs AS r
                  WHERE name = %s AND t.run_id = r.id AND r.branch = %s
                  ORDER BY t.test_id DESC
                  LIMIT 30'''
        tests = self._exec(sql, test_name, branch).fetchall()
        if interested_in_logs:
            self._populate_test_logs(tests, blob=False)
        return tests

    def get_one_run(self, run_id):
        sql = '''SELECT test_id, status, name, started, finished, branch
                   FROM tests JOIN runs ON (runs.id = tests.run_id)
                  WHERE run_id = %s
                  ORDER BY status, started'''
        tests = self._exec(sql, run_id).fetchall()
        if tests:
            branch = tests[0]['branch']
            for test in tests:
                test.pop('branch')
            self._populate_data_about_tests(tests, branch, blob=False)
        return tests

    def _populate_test_logs(self, tests, blob=False):
        if not tests:
            return

        def process_log(log):
            log.pop('test_id')
            if blob:
                log['log'] = self._str_from_blob(log['log'])
            return log

        tests_by_id = {int(test['test_id']): test for test in tests}
        sql = '''SELECT test_id, type, size, storage, stack_trace, patterns
                        {log_column}
                   FROM logs
                  WHERE test_id IN ({ids})
                  ORDER BY test_id, type'''.format(
            log_column=', log' if blob else '',
            ids=','.join(str(test_id) for test_id in tests_by_id))
        for test_id, rows in itertools.groupby(
                self._exec(sql).fetchall(), lambda row: row['test_id']):
            tests_by_id[test_id]['logs'] = [process_log(row) for row in rows]

    def _populate_data_about_tests(self, tests, branch, blob=False):
        self._populate_test_logs(tests, blob=blob)
        for test in tests:
            history = self.get_test_history(test['name'], branch)
            test['history'] = self.history_stats(history)

    def get_build_info(self, build_id):
        sql = '''SELECT run_id, status, started, finished, stderr, stdout,
                        features, is_release, branch, sha, title, requester
                   FROM builds JOIN runs ON (runs.id = builds.run_id)
                  WHERE build_id = %s
                  LIMIT 1'''
        res = self._exec(sql, build_id)
        build = res.fetchone()
        if build:
            build['stdout'] = self._str_from_blob(build['stdout'])
            build['stderr'] = self._str_from_blob(build['stderr'])
        return build

    def get_histoty_for_base_branch(self, test_id, branch):
        sql = 'SELECT name FROM tests WHERE test_id = %s LIMIT 1'
        res = self._exec(sql, test_id)
        test = res.fetchone()
        history = self.get_test_history(test['name'], branch)
        if len(history):
            test_id_base_branch = history[0]['test_id']
        else:
            test_id_base_branch = -1
        return {
            'history': self.history_stats(history),
            'test_id': test_id_base_branch
        }

    @classmethod
    def history_stats(cls, history):
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

    def get_one_test(self, test_id):
        sql = '''SELECT test_id, run_id, build_id, status, name, started,
                        finished, branch, sha, title, requester
                   FROM tests JOIN runs ON (runs.id = tests.run_id)
                  WHERE test_id = %s
                  LIMIT 1'''
        test = self._exec(sql, test_id).fetchone()
        if not test:
            return None
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
        return self._with_transaction(
            lambda: self.__do_schedule(branch=branch,
                                       sha=sha,
                                       title=title,
                                       builds=builds,
                                       tests=tests,
                                       requester=requester,
                                       is_nightly=is_nightly))

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
                   'is_release', 'remote')
        self._multi_insert(
            'tests', columns,
            ((run_id, test.build.build_id, test.name, test.category,
              int(is_nightly), test.is_release, test.is_remote)
             for test in tests))

        return run_id

    def last_nightly_run(self) -> typing.Dict[str, typing.Any]:
        """Returns the last nightly run."""
        return self._exec('''SELECT timestamp, sha
                               FROM runs
                              WHERE is_nightly
                              ORDER BY timestamp DESC
                              LIMIT 1''').fetchone()
