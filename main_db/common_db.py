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

        self.mydb = mysql.connector.connect(
            host=self.host,
            user=self.user, 
            passwd=self.passwd, 
            database=self.database,
            autocommit=commit,
        )
        self.mycursor = self.mydb.cursor(buffered=True, dictionary=True)

    def execute_sql(self, sql, val=()):
        # If we're not inside of a transaction check if connection is active and
        # reconnect if necessary.  If we are in a transaction, don't try to
        # reconnect since that would rollback what has been executed so far
        # without the caller knowing.
        if not self.mydb.in_transaction:
            self.mydb.ping(True)
        self.mycursor.execute(sql, val)
        return self.mycursor
 
    def get_github_login(self, token):
        sql = "SELECT name FROM users WHERE code=%s"
        result = self.execute_sql(sql, (token,))
        login = result.fetchone()
        if login:
            return login['name']  
        return None