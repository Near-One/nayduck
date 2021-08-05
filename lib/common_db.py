import gzip
import typing

import mysql.connector

from lib import config

_CONFIG = config.load('database')
_CONFIG.setdefault('host', '127.0.0.1')
_CONFIG.setdefault('user', 'nayduck')
_CONFIG.setdefault('database', 'nayduck')


class DB:

    def __init__(self):
        self.mydb = mysql.connector.connect(**_CONFIG, autocommit=True)
        self.mycursor = self.mydb.cursor(buffered=True, dictionary=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.mycursor.close()
        self.mydb.close()

    def _exec(self, sql: str, *val: typing.Any):
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

        This is a convenience wrapper around _exec which automatically formats
        an INSERT statement.  With this method, there's no need to manually
        count the `%s` in the statement template or making sure values are given
        in the correct order.

        Args:
            table: Table to insert a row into.
            kw: The column-value mapping for the row to insert.
        Returns:
            Id of the inserted row.
        """
        return self.__insert_impl('INSERT', table, kw)

    def _replace(self, table: str, **kw: typing.Any) -> int:
        """Like _insert but executes a REPLACE statement."""
        return self.__insert_impl('REPLACE', table, kw)

    def __insert_impl(self, verb: str, table: str,
                      fields: typing.Dict[str, typing.Any]) -> int:
        """Executes an INSERT or REPLACE statement."""
        columns, values = zip(*fields.items())
        sql = '{verb} INTO {table} ({columns}) VALUES ({placeholders})'.format(
            verb=verb,
            table=table,
            columns=', '.join(columns),
            placeholders=', '.join(['%s'] * len(columns)))
        return self._exec(sql, *values).lastrowid

    def _multi_insert(self,
                      table: str,
                      columns: typing.Collection[str],
                      rows: typing.Iterable[typing.Collection[typing.Any]],
                      *,
                      replace: bool = False) -> None:
        """Executes an INSERT statement adding multiple rows at once.

        Args:
            table: Table to insert rows into.
            columns: Names of columns to insert.
            rows: An iterable of rows to insert.  Each element must be
                a collection of the same length as columns count.  Values of
                each element correspond to columns at the same index.
            replace: Whether to uses REPLACE statement rather than INSERT.
        """
        vals = []
        for row in rows:
            assert len(row) == len(columns), row
            vals.extend(row)
        placeholders = '({})'.format(', '.join(['%s'] * len(columns)))
        count = len(vals) // len(columns)
        sql = '{verb} INTO {table} (`{columns}`) VALUES {placeholders}'.format(
            verb='REPLACE' if replace else 'INSERT',
            table=table,
            columns='`, `'.join(columns),
            placeholders=', '.join([placeholders] * count))
        self._exec(sql, *vals)

    def _with_transaction(
        self,
        callback: typing.Callable[[],
                                  typing.TypeVar('T')]) -> typing.TypeVar('T'):
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

    @classmethod
    def _blob_from_data(cls, data: typing.AnyStr) -> bytes:
        """Converts string or bytes to BLOB form for storage in database.

        If an argument is a string, encodes it into bytes using UTF-8 encoding.
        Any non-empty buffer is then compressed to save space though compressed
        data is returned only if it's shorter than uncompressed bytes.

        Args:
            data: Data, either str or bytes, to store in the database BLOB
                field.
        Returns:
            BLOB data to save in the database.
        """
        if isinstance(data, str):
            data = data.encode('utf-8')
        must_compress = data.startswith(b'\x1f\x8b')
        if must_compress or len(data) > 18:
            compressed = gzip.compress(data)
            if must_compress or len(compressed) < len(data):
                return compressed
        return data

    @classmethod
    def _str_from_blob(cls, blob: typing.Optional[bytes]) -> str:
        """Converts BLOB read from database into a string.

        This conversion is necessary because the data may be compressed in which
        case this method will decompress it.  The bytes are then decoded
        assuming UTF-8 encoding using a replacement character to handle errors.

        Args:
            blob: BLOB data read from the database (or None).
        Returns:
            String stored in the database.  None values are converted to empty
            strings.
        """
        if not blob:
            return ''
        if blob.startswith(b'\x1f\x8b'):
            blob = gzip.decompress(blob)
        return blob.decode('utf-8', 'replace')