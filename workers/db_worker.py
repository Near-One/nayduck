import mysql.connector
import random

import datetime
import os
import time
import sys

sys.path.append(os.path.abspath('../main_db'))
import common_db

class WorkerDB (common_db.DB):

    def __init__(self):
        self.host=os.environ['DB_HOST']
        self.user=os.environ['DB_USER']
        self.passwd=os.environ['DB_PASSWD']
        self.database=os.environ['DB']
        super().__init__(self.host, self.user, self.passwd, self.database)
    
    def get_pending_test(self, hostname):
        after = int(time.time())
        if "mocknet" in hostname:
            sql = "UPDATE tests t SET t.started = now(), t.status = 'RUNNING', t.hostname=%s  WHERE t.status = 'PENDING' and t.name LIKE '%mocknet%' and @tmp_id := t.test_id ORDER BY t.test_id LIMIT 1;"
        else:
            sql = '''UPDATE tests AS t, 
            (SELECT test_id FROM tests WHERE status = 'PENDING' and   
                    build_id in (select build_id from builds where status = 'BUILD DONE' or status = 'SKIPPED') and
                name NOT LIKE '%mocknet%' and select_after < %s ORDER BY priority, test_id LIMIT 1) AS id 
                SET t.started = now(), t.status = 'RUNNING', t.hostname=%s WHERE t.test_id=id.test_id and 
                @tmp_id := id.test_id'''
        res = self.execute_sql(sql, (after, hostname,))
        if res.rowcount == 0:
            return None
        sql = f'''SELECT t.test_id, t.run_id, t.build_id, r.sha, t.name, b.ip FROM tests t, runs r, builds b 
                  WHERE t.test_id = @tmp_id and t.run_id = r.id and  t.build_id = b.build_id'''
        result = self.execute_sql(sql, ())
        pending_test = result.fetchone()
        return pending_test

    def test_started(self, id):
        sql = "UPDATE tests SET started = now() WHERE test_id= %s"
        self.execute_sql(sql, (id,))

    def update_test_status(self, status, id):
        sql = "UPDATE tests SET finished = now(), status = %s WHERE test_id= %s"
        self.execute_sql(sql, (status, id))

    def save_short_logs(self, test_id, filename, file_size, data, storage, stack_trace, found_patterns):
        sql = "INSERT INTO logs (test_id, type, full_size, log, storage, stack_trace, patterns) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        self.execute_sql(sql, (test_id, filename, file_size, data, storage, stack_trace, found_patterns))

    def remark_test_pending(self, id):
        after = int(time.time()) + 3*60
        sql = "UPDATE tests SET started = null, hostname=null, status='PENDING', select_after=%s WHERE test_id= %s"
        self.execute_sql(sql, (after, id))

    def handle_restart(self, hostname):
        sql = "UPDATE tests SET started = null, status = 'PENDING', hostname=null  WHERE status = 'RUNNING' and hostname=%s"
        self.execute_sql(sql, (hostname,))
