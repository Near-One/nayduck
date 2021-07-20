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

        debug_builds = {}
        release_builds = {}

        # Into Tests
        after = int(time.time())
        for test in tests:
            if requester == 'NayDuck':
                priority = 1
            else:
                priority = 0
            if "--features" in test:
                features = test[test.find('--features'):]
            else:
                features = ""
            release = False
            remote = False
            build_status = 'PENDING'
            if '--remote' in test: 
                remote = True
            if 'mocknet' in test:
                remote = True
                build_status = 'SKIPPED'
            if '--release' in test:
                release = True
                if features not in release_builds:
                    build_id = self._insert('builds',
                                            run_id=run_id,
                                            status=build_status,
                                            features=features,
                                            is_release=1)
                    release_builds[features] = build_id
                else:
                    build_id = release_builds[features]
            else:
                if features not in debug_builds:
                    build_id = self._insert('builds',
                                            run_id=run_id,
                                            status=build_status,
                                            features=features,
                                            is_release=0)
                    build_id = result.lastrowid
                    debug_builds[features] = build_id
                else:
                    build_id = debug_builds[features]
            self._insert('tests',
                         run_id=run_id,
                         build_id=build_id,
                         name=test.strip(),
                         priority=priority,
                         release=int(release),
                         remote=int(remote))
        return run_id
        