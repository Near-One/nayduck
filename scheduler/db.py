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

        # Build for no features.
        sql = "INSERT INTO builds (run_id, build_status, features) values (%s, %s, %s)"
        result = self.execute_sql(sql, (run_id, "PENDING", ""))
        build_id = result.lastrowid

        builds = {"": build_id}


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
            if features not in builds:
                sql = "INSERT INTO builds (run_id, build_status, features) values (%s, %s, %s)"
                result = self.execute_sql(sql, (run_id, "PENDING", features))
                build_id = result.lastrowid
                builds[features] = build_id

            sql = "INSERT INTO tests (run_id, build_id, status, name, select_after, priority) values (%s, %s, %s, %s, %s, %s)"
            self.execute_sql(sql, (run_id, builds[features], "PENDING", test.strip(), after, priority))
        return run_id
        