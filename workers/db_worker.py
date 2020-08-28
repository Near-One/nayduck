import mysql.connector
import random

import datetime
import os


class DB ():

    def __init__(self):
        self.mydb, self.mycursor = self.connect()

    def connect(self):
        mydb = mysql.connector.connect(
            host=os.environ['DB_HOST'],
            user=os.environ['DB_USER'], 
            passwd=os.environ['DB_PASSWD'], 
            database=os.environ['DB']
        )
        mycursor = mydb.cursor(buffered=True, dictionary=True)
        return mydb, mycursor

    def execute_sql(self, sql, val):
        try:
            print(sql, val)
            self.mycursor.execute(sql, val)
            self.mydb.commit()
        except mysql.connector.errors.DatabaseError as e:
            try:
                print(e)
                self.mycursor.close()
                self.mydb.close()
            except Exception as ee:
                print(ee)
            self.mydb, self.mycursor = self.connect()
            self.mycursor.execute(sql, val)
            self.mydb.commit()
        except Exception as e:
            print(e)
            raise e
        return self.mycursor

    def get_pending_test(self, hostname):
        if "mocknet" in hostname:
            sql = "UPDATE tests t SET t.started = now(), t.status = 'RUNNING', t.hostname=%s  WHERE t.run_id in (select id from runs where build_status = 'BUILD DONE') and t.status = 'PENDING' and t.name LIKE '%mocknet%' and @tmp_id := t.test_id ORDER BY t.test_id LIMIT 1;"
        else:
            sql = "UPDATE tests t SET t.started = now(), t.status = 'RUNNING', t.hostname=%s  WHERE t.run_id in (select id from runs where build_status = 'BUILD DONE') and t.status = 'PENDING' and t.name NOT LIKE '%mocknet%' and @tmp_id := t.test_id ORDER BY t.test_id LIMIT 1;"
        res = self.execute_sql(sql, (hostname,))
        if res.rowcount == 0:
            return None
        sql = "SELECT t.test_id, t.run_id, r.sha, t.name, r.ip FROM tests t, runs r WHERE t.test_id = @tmp_id and t.run_id = r.id"
        result = self.execute_sql(sql, ())
        pending_test = result.fetchone()
        return pending_test

    def create_timestamp_for_test_started(self, id):
        sql = "UPDATE tests SET test_started = now() WHERE test_id= %s"
        self.execute_sql(sql, (id,))

    def update_test_status(self, status, id):
        sql = "UPDATE tests SET finished = now(), status = %s WHERE test_id= %s"
        self.execute_sql(sql, (status, id))

    def save_short_logs(self, test_id, filename, file_size, data, storage, stack_trace):
        sql = "INSERT INTO logs (test_id, type, full_size, log, storage, stack_trace) VALUES (%s, %s, %s, %s, %s, %s)"
        self.execute_sql(sql, (test_id, filename, file_size, data, storage, stack_trace))

    def handle_restart(self, hostname):
        sql = "UPDATE tests SET started = null, status = 'PENDING', hostname=null  WHERE status = 'RUNNING' and hostname=%s"
        self.execute_sql(sql, (hostname,))
