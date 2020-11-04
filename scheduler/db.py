import mysql.connector
import random

import datetime
import os
import sys
import time

sys.path.append('main_db')

from main_db.main_db import MainDB

class SchedulerDB (MainDB):

    def __init__(self):
        self.host=os.environ['NAYDUCK_DB_HOST']
        self.user=os.environ['NAYDUCK_DB_USER']
        self.passwd=os.environ['NAYDUCK_DB_PASSWD']
        self.database=os.environ['NAYDUCK_DB']
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
        