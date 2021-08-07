import collections
import os
import random
import string
import sys
import typing

sys.path.append(os.path.abspath('../main_db'))
import common_db  # pylint: disable=wrong-import-position


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
        result = self._exec(sql, test_id)
        res = result.fetchone()
        return self.get_test_history(res['name'],
                                     res['branch'],
                                     interested_in_logs=True)

    def get_test_history(self, test_name, branch, interested_in_logs=False):
        sql = '''SELECT t.test_id, r.requester, r.title, t.status, t.started,
                        t.finished, r.branch, r.sha
                   FROM tests AS t, runs AS r
                  WHERE name = %s AND t.run_id = r.id AND r.branch = %s
                  ORDER BY t.test_id DESC
                  LIMIT 30'''
        result = self._exec(sql, test_name, branch)
        tests = result.fetchall()
        for test in tests:
            if interested_in_logs:
                sql = '''SELECT type, size, storage, stack_trace, patterns
                           FROM logs
                          WHERE test_id = %s
                          ORDER BY type'''
                test['logs'] = self._exec(sql, test['test_id']).fetchall()
        return tests

    def get_one_run(self, run_id):
        run_data = self.get_data_about_run(run_id)
        branch = run_data['branch']

        sql = '''SELECT build_id, is_release, features
                   FROM builds
                  WHERE run_id = %s'''
        res = self._exec(sql, run_id)
        builds_dict = dict((build['build_id'], build)
                           for build in (res.fetchall() or self._NO_BUILDS))

        sql = '''SELECT *
                   FROM tests
                  WHERE run_id = %s
                  ORDER BY status, started'''
        res = self._exec(sql, run_id)
        a_run = res.fetchall()
        for test in a_run:
            if test['build_id'] is None:
                test['build_id'] = 0
            test['build'] = builds_dict[test['build_id']]
            test.update(self.get_data_about_test(test, branch, blob=False))
        return a_run

    def get_data_about_test(self, test, branch, blob=False):
        columns = 'type, size, storage, stack_trace, patterns'
        if blob:
            columns += ', log'
        sql = f'SELECT {columns} FROM logs WHERE test_id = %s ORDER BY type'
        test['logs'] = logs = self._exec(sql, test['test_id']).fetchall()
        if blob:
            for log in logs:
                log['log'] = self._str_from_blob(log['log'])
        test['cmd'] = test['name']
        if '--features' in test['name']:
            test['name'] = test['name'][:test['name'].find('--features')]
        test['name'] = ' '.join(
            word for word in test['name'].split() if not word.startswith('--'))
        history = self.get_test_history(test['cmd'], branch)
        test['history'] = self.history_stats(history)
        return test

    def get_data_about_run(self, run_id):
        sql = 'SELECT * FROM runs WHERE id = %s LIMIT 1'
        res = self._exec(sql, run_id)
        return res.fetchone()

    def get_build_info(self, build_id):
        sql = 'SELECT * FROM builds WHERE build_id = %s LIMIT 1'
        res = self._exec(sql, build_id)
        build = res.fetchone()
        build['stdout'] = self._str_from_blob(build['stdout'])
        build['stderr'] = self._str_from_blob(build['stderr'])
        run = self.get_data_about_run(build['run_id'])
        build.update(run)
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
        res = {'PASSED': 0, 'FAILED': 0, 'OTHER': 0}
        for hist in history:
            if hist['status'] == 'PASSED':
                res['PASSED'] += 1
            elif hist['status'] in ('FAILED', 'BUILD FAILED', 'TIMEOUT'):
                res['FAILED'] += 1
            else:
                res['OTHER'] += 1
        return res

    def get_one_test(self, test_id):
        sql = '''SELECT test_id, run_id, build_id, status, name, started,
                        finished
                   FROM tests WHERE test_id = %s
                  LIMIT 1'''
        test = self._exec(sql, test_id).fetchone()
        if not test:
            return None
        test.update(self.get_data_about_run(test['run_id']))
        return self.get_data_about_test(test, test['branch'], blob=True)

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
