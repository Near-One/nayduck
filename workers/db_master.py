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
    
    def get_new_run(self, ip_address):
        sql = "UPDATE runs SET build_started = now(), build_status = 'BUILDING', ip=%s  WHERE build_status = 'BUILD PENDING' and @tmp_id := id ORDER BY id LIMIT 1 "
        res = self.execute_sql(sql, (ip_address,))
        if res.rowcount == 0:
            return None
        sql = "SELECT id, sha, type FROM runs WHERE id = @tmp_id"
        result = self.execute_sql(sql, ())
        new_run = result.fetchone()
        return new_run

    def update_run_status(self, status, run_id):
        sql = "UPDATE runs SET build_finished = now(), build_status = %s WHERE id=%s"
        self.execute_sql(sql, (status, run_id))
        if status == "BUILD FAILED":
            sql = "UPDATE tests SET status = 'CANCELED' WHERE run_id=%s and status='PENDING'"
            self.execute_sql(sql, (run_id,))

    def handle_restart(self, ip_address):
        sql = "UPDATE runs SET build_started = null, build_status = 'BUILD PENDING', ip=null  WHERE build_status = 'BUILDING' and ip=%s"
        self.execute_sql(sql, (ip_address,))

    def get_all_finished_runs(self, ip_address):
        sql = "SELECT build_id FROM builds WHERE ip = %s ORDER BY build_id desc LIMIT 20"
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

    def save_build_logs(self, run_id, err, out):
        sql = "UPDATE runs SET build_stderr=%s, build_stdout = %s WHERE id=%s"
        self.execute_sql(sql, (err, out, run_id)) 
       