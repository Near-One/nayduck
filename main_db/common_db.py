import mysql.connector
import random
import string
import time

import datetime
import os


class DB ():
    def __init__(self, *, commit=True):
        self.host = os.environ['DB_HOST']
        self.user = os.environ['DB_USER']
        self.passwd = os.environ['DB_PASSWD']
        self.database = os.environ['DB']
        self.commit = commit
        self.mydb, self.mycursor = self.connect()

    def connect(self):
        mydb = mysql.connector.connect(
            host=self.host,
            user=self.user, 
            passwd=self.passwd, 
            database=self.database,
            autocommit=self.commit,
        )
        mycursor = mydb.cursor(buffered=True, dictionary=True)
        return mydb, mycursor

    def execute_sql(self, sql, val=()):
        try:
            self.mycursor.execute(sql, val)
            if self.commit:
                self.mydb.commit()
        except Exception as e:
            try:
                print(sql, val)
                print(e)
                self.mycursor.close()
                self.mydb.close()
            except Exception as ee:
                print(ee)
                raise ee
            self.mydb, self.mycursor = self.connect()
            self.mycursor.execute(sql, val)
            if self.commit:
                self.mydb.commit()
        return self.mycursor
 
    def get_github_login(self, token):
        sql = "SELECT name FROM users WHERE code=%s"
        result = self.execute_sql(sql, (token,))
        login = result.fetchone()
        if login:
            return login['name']  
        return None