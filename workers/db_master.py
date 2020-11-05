import mysql.connector
import random

import datetime
import os
import sys

sys.path.append(os.path.abspath('../main_db'))
import common_db

class MasterDB (common_db.DB):

    def __init__(self):
        self.host=os.environ['DB_HOST']
        self.user=os.environ['DB_USER']
        self.passwd=os.environ['DB_PASSWD']
        self.database=os.environ['DB']
        super().__init__(self.host, self.user, self.passwd, self.database)
    
    def get_new_build(self, ip_address):
        sql = "UPDATE builds SET started = now(), status = 'BUILDING', ip=%s  WHERE status = 'PENDING' and @tmp_id := build_id ORDER BY build_id LIMIT 1 "
        res = self.execute_sql(sql, (ip_address,))
        if res.rowcount == 0:
            return None
        sql = "SELECT b.build_id, r.sha, b.features, b.is_release FROM builds as b, runs as r WHERE b.build_id = @tmp_id and b.run_id = r.id"
        result = self.execute_sql(sql, ())
        new_run = result.fetchone()
        return new_run

    def update_run_status(self, build_id, status, err, out):
        sql = "UPDATE builds SET finished = now(), status = %s, stderr=%s, stdout = %s WHERE build_id=%s"
        self.execute_sql(sql, (status, err, out, build_id))
        if status == "BUILD FAILED":
            sql = "UPDATE tests SET status = 'CANCELED' WHERE build_id=%s and status='PENDING'"
            self.execute_sql(sql, (build_id,))

    def handle_restart(self, ip_address):
        sql = "UPDATE builds SET started = null, status = 'PENDING', ip=null  WHERE status = 'BUILDING' and ip=%s"
        self.execute_sql(sql, (ip_address,))

    def get_builds_with_finished_tests(self, ip_address):
        sql = "SELECT build_id FROM builds WHERE ip=%s ORDER BY build_id desc LIMIT 20"
        result = self.execute_sql(sql, (ip_address,))
        builds = result.fetchall()
        finished_runs = []
        for build in builds:
            sql = "SELECT count(IF(status='PENDING' or status='RUNNING',1,NULL)) AS still_going FROM tests WHERE build_id = %s"
            result = self.execute_sql(sql, (build['build_id'],))
            going = result.fetchone()
            if going['still_going'] == 0:
                finished_runs.append(build['build_id'])
        return finished_runs

       