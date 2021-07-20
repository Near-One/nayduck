import mysql.connector
import random

import datetime
import os
import sys
import time
import typing

sys.path.append(os.path.abspath('../main_db'))
import common_db

class SchedulerDB (common_db.DB):
    def scheduling_a_run(self, branch: str, sha: str, user: str, title: str,
                         tests: typing.Sequence[str], requester: str):
        return self._with_transaction(lambda: self.__do_schedule(
            branch, sha, user, title, tests, requester))

    def __do_schedule(self, branch: str, sha: str, user: str, title: str,
                      tests: typing.Sequence[str], requester: str):
        # Into Runs
        run_id = self._insert('runs',
                              branch=branch,
                              sha=sha,
                              user=user,
                              title=title,
                              requester=requester)

        # Into Tests
        builds = {}
        after = int(time.time())
        priority = int(requester == 'NayDuck')
        for test in tests:
            pos = test.find('--features')
            features = '' if pos < 0 else test[pos:]
            release = '--release' in test
            remote = '--remote' in test
            build_status = 'PENDING'
            if 'mocknet' in test:
                remote = True
                build_status = 'SKIPPED'
            build_id = builds.get((release, features))
            if build_id is None:
                build_id = self._insert('builds',
                                        run_id=run_id,
                                        status=build_status,
                                        features=features,
                                        is_release=int(release))
                builds[(release, features)] = build_id
            self._insert('tests',
                         run_id=run_id,
                         build_id=build_id,
                         name=test.strip(),
                         priority=priority,
                         release=int(release),
                         remote=int(remote))
        return run_id
        