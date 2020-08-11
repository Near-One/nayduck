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
        sql = "UPDATE tests SET started = now(), status = 'RUNNING', hostname=%s  WHERE status = 'PENDING' and @tmp_id := test_id ORDER BY test_id LIMIT 1 "
        res = self.execute_sql(sql, (hostname,))
        if res.rowcount == 0:
            return None
        sql = "SELECT t.test_id, t.run_id, r.sha, t.name FROM tests t, runs r WHERE t.test_id = @tmp_id and t.run_id = r.id"
        result = self.execute_sql(sql, ())
        pending_test = result.fetchone()
        return pending_test

    def update_test_status(self, status, id):
        sql = "UPDATE tests SET finished = now(), status = %s WHERE test_id= %s"
        self.execute_sql(sql, (status, id))

    def scheduling_a_run(self, branch, sha, user, title, tests):
        sql = "INSERT INTO runs (branch, sha, user, title) values (%s, %s, %s, %s)"
        result = self.execute_sql(sql, (branch, sha, user, title))
        run_id = result.lastrowid
        for test in tests:
            sql = "INSERT INTO tests (run_id, status, name) values (%s, %s, %s)"
            self.execute_sql(sql, (run_id, "PENDING", test.strip()))
        return run_id

    def get_all_runs(self):
        sql = "SELECT * FROM runs ORDER BY id desc LIMIT 100"
        res = self.execute_sql(sql, ())
        all = res.fetchall()
        all_runs = []
        for a in all:
            sql = "select count(IF(status='PENDING',1,NULL)) AS pending,  count(IF(status='RUNNING',1,NULL)) AS running,  count(IF(status='PASSED',1,NULL)) AS passed,  count(IF(status='IGNORED',1,NULL)) AS ignored,  count(IF(status='FAILED',1,NULL)) AS failed,  count(IF(status='BUILD FAILED',1,NULL)) AS build_failed,  count(IF(status='CANCELED',1,NULL)) AS canceled,  count(IF(status='TIMEOUT',1,NULL)) AS timeout from tests where run_id = %s"
            res = self.execute_sql(sql, (a['id'],))
            counts = res.fetchone()
            a.update(counts)
            all_runs.append(a)
        return all_runs

    def get_test_history_by_id(self, test_id):
        sql = "SELECT t.name, r.branch FROM tests as t, runs as r WHERE t.test_id=%s and r.id = t.run_id"
        result = self.execute_sql(sql, (test_id,))
        res = result.fetchone()
        return self.get_test_history(res["name"], res["branch"])
        
    def get_test_history(self, test_name, branch):
        sql = "SELECT t.test_id, r.user, r.title, t.status, t.started, t.finished, r.branch, r.sha FROM tests as t, runs as r WHERE name=%s and t.run_id = r.id and r.branch=%s ORDER BY t.test_id desc LIMIT 30"
        result = self.execute_sql(sql, (test_name, branch))
        tests = result.fetchall()
        for test in tests:
            if test["finished"] != None and test["started"] != None:
                test["run_time"] = str(test["finished"] - test["started"])
            sql = "SELECT type, full_size, storage, stack_trace from logs WHERE test_id = %s ORDER BY type"
            res = self.execute_sql(sql, (test["test_id"],))
            logs = res.fetchall()
            test["logs"] = []
            for l in logs:
                test["logs"].append(l)
        return tests
            
    def get_one_run(self, run_id):
        run_data = self.get_data_about_run(run_id)
        branch = run_data["branch"] 
        sql = "SELECT * FROM tests WHERE run_id=%s"
        res = self.execute_sql(sql, (run_id,))
        a_run = res.fetchall()
        for test in a_run:
            test.update(self.get_data_about_test(test, branch, blob=False))
        return a_run

    def get_data_about_test(self, test, branch, blob=False):
        if blob:
            sql = "SELECT * from logs WHERE test_id = %s ORDER BY type"
        else:
            sql = "SELECT type, full_size, storage, stack_trace from logs WHERE test_id = %s ORDER BY type"
        res = self.execute_sql(sql, (test["test_id"],))
        logs = res.fetchall()
        test["logs"] = {}
        for l in logs:
            if "log" in l:
                l["log"] = l["log"].decode()
            test["logs"][l["type"]] = l
        spl = test["name"].split(' ')
        test["type"] = spl[0]
        if spl[1].startswith("--"):
            test["args"] = spl[1]
            test["test"] = ' '.join(spl[2:])
        else:
            test["test"] = ' '.join(spl[1:])
        if test["finished"] != None and test["started"] != None:
            test["run_time"] = str(test["finished"] - test["started"])
        history = self.get_test_history(test["name"], branch)
        test["history"] = self.history_stats(history)
        return test

    def get_data_about_run(self, run_id):
        sql = "SELECT * from runs WHERE id = %s"
        res = self.execute_sql(sql, (run_id,))
        r = res.fetchone()
        return r
                    
    def get_histoty_for_base_branch(self, test_id, branch):
        sql = "SELECT name FROM tests WHERE test_id=%s"
        res = self.execute_sql(sql, (test_id,))
        test = res.fetchone()
        history = self.get_test_history(test["name"], branch)
        if len(history):
            test_id_base_branch = history[0]["test_id"]
        else:
            test_id_base_branch = -1
        return {"history": self.history_stats(history), "test_id": test_id_base_branch}
        
    def history_stats(self, history):
        res = {"PASSED": 0, "FAILED": 0, "OTHER": 0}
        for h in history:
            if h["status"] == "PASSED":
                res["PASSED"] += 1
            elif h["status"] == "FAILED" or h["status"] == "BUILD FAILED" or h["status"] == "TIMEOUT":
                res["FAILED"] += 1
            else:
                res["OTHER"] += 1
        return res
        
    def get_one_test(self, test_id):
        sql = "SELECT * FROM tests WHERE test_id=%s"
        res = self.execute_sql(sql, (test_id,))
        tests = res.fetchall()
        for test in tests:
            run_data = self.get_data_about_run(test["run_id"])
            new_data = self.get_data_about_test(test, run_data["branch"], blob=True) 
            test.update(new_data)
            test.update(run_data)       
        return tests
            
    def save_short_logs(self, test_id, filename, file_size, data, storage, stack_trace):
        sql = "INSERT INTO logs (test_id, type, full_size, log, storage, stack_trace) VALUES (%s, %s, %s, %s, %s, %s)"
        self.execute_sql(sql, (test_id, filename, file_size, data, storage, stack_trace))

    def handle_restart(self, hostname):
        sql = "UPDATE tests SET started = null, status = 'PENDING', hostname=null  WHERE status = 'RUNNING' and hostname=%s"
        self.execute_sql(sql, (hostname,))
