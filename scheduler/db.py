import mysql.connector
import random

import datetime
import os
import sys
import time

sys.path.append(os.path.abspath('../main_db'))
import common_db

class SchedulerDB (common_db.DB):
    def __init__(self):
        super().__init__(commit=False)

    def scheduling_a_run(self, branch, sha, user, title, tests, requester):
        # Into Runs
        sql = "START TRANSACTION"
        self._execute_sql(sql)
        
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
        sql = "COMMIT"
        self._execute_sql(sql)
        return run_id
        