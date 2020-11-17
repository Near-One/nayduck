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
        self.host=os.environ['DB_HOST']
        self.user=os.environ['DB_USER']
        self.passwd=os.environ['DB_PASSWD']
        self.database=os.environ['DB']
        super().__init__(self.host, self.user, self.passwd, self.database)

    def scheduling_a_run(self, branch, sha, user, title, tests, requester):
        # Into Runs
        sql = "INSERT INTO runs (branch, sha, user, title, requester, timestamp) values (%s, %s, %s, %s, %s, now())"
        result = self.execute_sql(sql, (branch, sha, user, title, requester))
        run_id = result.lastrowid

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
            if '--remote' in test or 'mocknet' in test:
                remote = True
                build_status = 'SKIPPED'
            if '--release' in test:
                release = True
                if features not in release_builds:
                    sql = "INSERT INTO builds (run_id, status, features, is_release) values (%s, %s, %s, %s)"
                    result = self.execute_sql(sql, (run_id, build_status, features, 1))
                    build_id = result.lastrowid
                    release_builds[features] = build_id
                else:
                    build_id = release_builds[features]
            else:
                if features not in debug_builds:
                    sql = "INSERT INTO builds (run_id, status, features) values (%s, %s, %s)"
                    result = self.execute_sql(sql, (run_id, build_status, features))
                    build_id = result.lastrowid
                    debug_builds[features] = build_id
                else:
                    build_id = debug_builds[features]
            sql = "INSERT INTO tests (run_id, build_id, status, name, select_after, priority, is_release, remote) values (%s, %s, %s, %s, %s, %s, %s, %s)"
            self.execute_sql(sql, (run_id, build_id, "PENDING", test.strip(), after, priority, release, remote))
        return run_id
        