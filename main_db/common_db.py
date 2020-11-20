import mysql.connector
import random
import string
import time

import datetime
import os


class DB ():

    def __init__(self, host, user, passwd, database):
        self.host=host
        self.user=user 
        self.passwd=passwd
        self.database=database
        self.mydb, self.mycursor = self.connect(host, user, passwd, database)

    def connect(self, host, user, passwd, database):
        mydb = mysql.connector.connect(
            host=host,
            user=user, 
            passwd=passwd, 
            database=database
        )
        mycursor = mydb.cursor(buffered=True, dictionary=True)
        return mydb, mycursor

    def execute_sql(self, sql, val=()):
        try:
            self.mycursor.execute(sql, val)
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
            self.mydb, self.mycursor = self.connect(self.host, self.user, self.passwd, self.database)
            self.mycursor.execute(sql, val)
            self.mydb.commit()
        return self.mycursor
 
    def get_github_login(self, token):
        sql = "SELECT name FROM users WHERE code=%s"
        result = self.execute_sql(sql, (token,))
        login = result.fetchone()
        if login:
            return login['name']  
        return None