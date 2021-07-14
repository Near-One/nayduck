import mysql.connector
import random
import string
import time
import typing

import datetime
import os


class DB ():
    def __init__(self):
        self.host = os.environ['DB_HOST']
        self.user = os.environ['DB_USER']
        self.passwd = os.environ['DB_PASSWD']
        self.database = os.environ['DB']

        self.mydb = mysql.connector.connect(
            host=self.host,
            user=self.user, 
            passwd=self.passwd, 
            database=self.database,
            autocommit=True,
        )
        self.mycursor = self.mydb.cursor(buffered=True, dictionary=True)

    def _execute_sql(self, sql: str, val: typing.Sequence[typing.Any]=()):
        """Executes given SQL statement.

        Args:
            sql: Template of the statement to execute.  Any `%s` placeholders in
                the template will be replaced by corresponding values in val.
            val: Values it substitute in the statement template.
        Returns:
            A MySQL cursor which can be used to retrieve result.
        """
        # If we're not inside of a transaction check if connection is active and
        # reconnect if necessary.  If we are in a transaction, don't try to
        # reconnect since that would rollback what has been executed so far
        # without the caller knowing.
        if not self.mydb.in_transaction:
            self.mydb.ping(True)
        self.mycursor.execute(sql, val)
        return self.mycursor

    def _insert(self, table: str, **kw: typing.Any) -> int:
        """Executes an INSERT statement.

        This is a convenience wrapper around _execute_sql which automatically
        formats an INSERT statement.  With this method, there's no need to
        manually count the `%s` in the statement template or making sure values
        are given in the correct order.

        Args:
            table: Table to insert a row into.
            kw: The column-value mapping for the row to insert.
        Returns:
            Id of the inserted row.
        """
        columns, values = zip(*kw.items())
        sql = 'INSERT INTO {table} ({columns}) VALUES ({placeholders})'.format(
            table=table,
            columns=', '.join(columns),
            placeholders=', '.join(['%s'] * len(columns)))
        cursor = self._execute_sql(sql, values)
        return cursor.lastrowid

    def _with_transaction(
            self,
            callback: typing.Callable[[], typing.TypeVar('T')]
    ) -> typing.TypeVar('T'):
        """Executes callback inside of a SQL transaction.

        Starts a transaction before calling the callback and ends it once the
        callback finishes.  If the callback raises an exception, the method
        rolls back the transaction.  Otherwise, it commits the transaction and
        returns whatever value the callback returned.

        Raises an exception if transaction is already active.

        Args:
            callback: Code to execute within the transaction.
        Returns:
            Whatever callback returns.
        """
        self.mydb.start_transaction()
        commit = False
        try:
            result = callback()
            commit = True
            return result
        finally:
            if commit:
                self.mydb.commit()
            else:
                self.mydb.rollback()
