import mysql.connector
import random
import string
import time

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
            self.mycursor.execute(sql, val)
            self.mydb.commit()
        except mysql.connector.errors.DatabaseError as e:
            try:
                print(sql, val)
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
        after = int(time.time())
        if "mocknet" in hostname:
            sql = "UPDATE tests SET started = now(), status = 'RUNNING', hostname=%s  WHERE status = 'PENDING' and name LIKE '%mocknet%' and select_after < %s and @tmp_id := test_id ORDER BY test_id LIMIT 1 "
        else:
            sql = "UPDATE tests AS a, (SELECT test_id FROM tests WHERE status = 'PENDING' and name NOT LIKE '%mocknet%' and select_after < %s ORDER BY priority, test_id LIMIT 1) AS b SET a.started = now(), a.status = 'RUNNING', a.hostname=%s WHERE a.test_id=b.test_id and @tmp_id := b.test_id"
        res = self.execute_sql(sql, (after, hostname))
        if res.rowcount == 0:
            return None
        sql = "SELECT t.test_id, t.run_id, r.sha, t.name FROM tests t, runs r WHERE t.test_id = @tmp_id and t.run_id = r.id"
        result = self.execute_sql(sql, ())
        pending_test = result.fetchone()
        return pending_test

    def create_timestamp_for_test_started(self, id):
        sql = "UPDATE tests SET test_started = now() WHERE test_id= %s"
        self.execute_sql(sql, (id,))

    def update_test_status(self, status, id):
        sql = "UPDATE tests SET finished = now(), status = %s WHERE test_id= %s"
        self.execute_sql(sql, (status, id))

    def remark_test_pending(self, id):
        after = int(time.time()) + 3*60
        sql = "UPDATE tests SET started = null, hostname=null, status='PENDING', select_after=%s WHERE test_id= %s"
        self.execute_sql(sql, (after, id))

    def cancel_the_run(self, run_id, status="CANCELED"):
        sql = "UPDATE tests SET finished = now(), status = %s WHERE run_id= %s and status='PENDING'"
        self.execute_sql(sql, (status, run_id))

    def scheduling_a_run(self, branch, sha, user, title, tests, requester, run_type):
        sql = "INSERT INTO runs (branch, sha, user, title, requester, type) values (%s, %s, %s, %s, %s, %s)"
        result = self.execute_sql(sql, (branch, sha, user, title, requester, run_type))
        run_id = result.lastrowid
        after = int(time.time())
        for test in tests:
            if requester == 'NayDuck':
                priority = 1
            else:
                priority = 0
            sql = "INSERT INTO tests (run_id, status, name, select_after, priority) values (%s, %s, %s, %s, %s)"
            self.execute_sql(sql, (run_id, "PENDING", test.strip(), after, priority))
        return run_id

    def get_auth_code(self, login):
        sql = "SELECT id, code FROM users WHERE name=%s"
        result = self.execute_sql(sql, (login,))
        user = result.fetchone()
        if user:
            code = user['code']
        else:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=20))
            sql = "INSERT INTO users (name, code) values (%s, %s)"
            self.execute_sql(sql, (login, code))
        return code
 
    def get_github_login(self, token):
        sql = "SELECT name FROM users WHERE code=%s"
        result = self.execute_sql(sql, (token,))
        login = result.fetchone()
        if login:
            return login['name']  
        return None

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
        sql = "SELECT t.test_id, r.user, r.title, t.status, t.started, t.finished, t.test_started, r.branch, r.sha FROM tests as t, runs as r WHERE name=%s and t.run_id = r.id and r.branch=%s ORDER BY t.test_id desc LIMIT 30"
        result = self.execute_sql(sql, (test_name, branch))
        tests = result.fetchall()
        for test in tests:
            if test["finished"] != None and test["started"] != None:
                test["run_time"] = str(test["finished"] - test["started"])
            if test["test_started"] != None and test["finished"] != None:
                test["test_time"] = str(test["finished"] - test["test_started"])
            sql = "SELECT type, full_size, storage, stack_trace, patterns from logs WHERE test_id = %s ORDER BY type"
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
            sql = "SELECT type, full_size, storage, stack_trace, patterns from logs WHERE test_id = %s ORDER BY type"
        res = self.execute_sql(sql, (test["test_id"],))
        logs = res.fetchall()
        test["logs"] = {}
        for l in logs:
            if "log" in l:
                l["log"] = l["log"].decode()
            test["logs"][l["type"]] = l
        spl = test["name"].split(' ')
        test["type"] = spl[0]
        args = []
        test_l = []
        for s in spl:
            if s.startswith("--"):
                args.append(s)
            else:
                test_l.append(s)
        test["args"] = ' '.join(args)
        test["test"] = ' '.join(test_l)
        if test["finished"] != None and test["started"] != None:
            test["run_time"] = str(test["finished"] - test["started"])
        if test["test_started"] != None and test["finished"] != None:
            test["test_time"] = str(test["finished"] - test["test_started"])
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
            
    def save_short_logs(self, test_id, filename, file_size, data, storage, stack_trace, found_patterns):
        sql = "INSERT INTO logs (test_id, type, full_size, log, storage, stack_trace, patterns) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        self.execute_sql(sql, (test_id, filename, file_size, data, storage, stack_trace, found_patterns))

    def handle_restart(self, hostname):
        sql = "UPDATE tests SET started = null, status = 'PENDING', hostname=null  WHERE status = 'RUNNING' and hostname=%s"
        self.execute_sql(sql, (hostname,))
