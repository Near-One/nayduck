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


    def scheduling_a_run(self, branch, sha, user, title, tests, requester, run_type):
        sql = "INSERT INTO runs (branch, sha, user, title, requester, type, build_status, build_requested) values (%s, %s, %s, %s, %s, %s, %s, now())"
        result = self.execute_sql(sql, (branch, sha, user, title, requester, run_type, "BUILD PENDING"))
        run_id = result.lastrowid
        for test in tests:
            sql = "INSERT INTO tests (run_id, status, name) values (%s, %s, %s)"
            self.execute_sql(sql, (run_id, "PENDING", test.strip()))
        return run_id
