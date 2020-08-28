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
        sql = "SELECT id FROM runs WHERE ip = %s ORDER BY id desc LIMIT 20"
        result = self.execute_sql(sql, (ip_address,))
        runs = result.fetchall()
        finished_runs = []
        for run in runs:
            sql = "SELECT count(IF(status='PENDING' or status='RUNNING',1,NULL)) AS still_going FROM tests WHERE run_id = %s"
            result = self.execute_sql(sql, (run['id'],))
            going = result.fetchone()
            if going['still_going'] == 0:
                finished_runs.append(run['id'])
        return finished_runs

    def save_build_logs(self, run_id, err, out):
        sql = "UPDATE runs SET build_stderr=%s, build_stdout = %s WHERE id=%s"
        self.execute_sql(sql, (err, out, run_id)) 
       