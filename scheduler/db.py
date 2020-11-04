import mysql.connector
import random

import datetime
import os
import sys

sys.path.append('main_db')

from main_db.main_db import MainDB

class SchedulerDB (MainDB):

    def __init__(self):
        self.host=os.environ['NAYDUCK_DB_HOST']
        self.user=os.environ['NAYDUCK_DB_USER']
        self.passwd=os.environ['NAYDUCK_DB_PASSWD']
        self.database=os.environ['NAYDUCK_DB']
        super().__init__(self.host, self.user, self.passwd, self.database)

    def scheduling_a_run(self, branch, sha, user, title, tests, requester, run_type):
        sql = "INSERT INTO runs (branch, sha, user, title, requester, type, build_status, build_requested) values (%s, %s, %s, %s, %s, %s, %s, now())"
        result = self.execute_sql(sql, (branch, sha, user, title, requester, run_type, "BUILD PENDING"))
        run_id = result.lastrowid
        for test in tests:
            sql = "INSERT INTO tests (run_id, status, name) values (%s, %s, %s)"
            self.execute_sql(sql, (run_id, "PENDING", test.strip()))
        return run_id
