import gzip
import time
import typing

import sqlalchemy

from lib import config

_Row = typing.Any
_Dict = typing.Dict[str, typing.Any]

_T = typing.TypeVar('_T')
_D = typing.TypeVar('_D', bound='DB')


def __create_engine() -> sqlalchemy.engine.Engine:
    cfg = config.load('database')
    cfg.setdefault('database', 'nayduck')
    cfg.setdefault('username', 'nayduck')
    cfg.setdefault('query', {}).update({'client_encoding': 'utf8'})
    url = sqlalchemy.engine.URL.create('postgresql', **cfg)
    return sqlalchemy.create_engine(url,
                                    future=True,
                                    pool_size=1,
                                    pool_recycle=4 * 3600,
                                    max_overflow=20,
                                    encoding='utf-8')


_ENGINE = __create_engine()


class DB:

    def __init__(self) -> None:
        self.__conn = _ENGINE.connect()
        self.__in_transaction = False

    def __enter__(self: _D) -> _D:
        return self

    def __exit__(self, *_: typing.Any) -> None:
        self.__conn.close()

    def _exec(self, sql: str,
              **kw: typing.Any) -> sqlalchemy.engine.cursor.CursorResult:
        """Executes given SQL statement.

        Args:
            sql: Template of the statement to execute.  Any `:name` placeholders
                in the template will be replaced by corresponding keyword
                arguments
            kw: Keyword arguments to put in place of placeholders in the query.
        Returns:
            A cursor result which can be used to retrieve result.
        """
        stmt = sqlalchemy.text(sql).bindparams(**kw)

        def execute() -> sqlalchemy.engine.cursor.CursorResult:
            return self.__conn.execute(stmt)

        # _in_transaction takes care of retries on disconnect.
        return self._in_transaction(execute)

    def _fetch_one(self, sql: str, **kw: typing.Any) -> typing.Optional[_Dict]:
        """Returns first row of a query as dictionary."""
        row = self._exec(sql, **kw).first()
        return row and self._to_dict(row)

    def _fetch_all(self, sql: str, **kw: typing.Any) -> typing.Sequence[_Dict]:
        """Returns iterator over rows of a query as dictionaries."""
        return tuple(self._to_dict(row) for row in self._exec(sql, **kw))

    def _in_transaction(self, callback: typing.Callable[..., _T],
                        *args: typing.Any, **kw: typing.Any) -> _T:
        """Executes callback inside of an SQL transaction.

        Postpones committing queries until the callback finishes.  If callback
        terminates by raising an exception rolls the transaction back rather
        than committing it.  Note that the callback may be invoked multiple
        times if disconnection happens while communicating with the database.

        If we’re already inside of a transaction (i.e. this method is called
        recursively), simply executes the callback.

        Args:
            callback: Code to execute within the transaction.
            args: Positional arguments passed to the callback.
            kw: Keyword arguments passed to the callback.
        Returns:
            Whatever callback returns.
        """
        if self.__in_transaction:
            return callback(*args, **kw)

        self.__in_transaction = True
        try:
            retry = 0
            while True:
                try:
                    result = callback(*args, **kw)
                    self.__conn.commit()
                    return result
                except BaseException as ex:
                    self.__conn.rollback()
                    if not (retry < 2 and
                            isinstance(ex, sqlalchemy.exc.DBAPIError) and
                            ex.connection_invalidated):  # pylint: disable=no-member
                        raise
                    print(f'Got {ex}; retrying')
                    time.sleep(1 + retry * 4)
                    retry += 1
                    self.__conn = _ENGINE.connect()
        finally:
            self.__in_transaction = False

    def _insert(self,
                table: str,
                id_column: typing.Optional[str] = None,
                **kw: typing.Any) -> int:
        """Executes an INSERT statement.

        This is a convenience wrapper around _exec which automatically formats
        an INSERT statement.  With this method, there's no need to manually
        count the `%s` in the statement template or making sure values are given
        in the correct order.

        Args:
            table: Table to insert a row into.
            id_column: Name of an ID column if one exists in the table.  If
                given, value of that column will be returned after the insert.
            kw: The column-value mapping for the row to insert.
        Returns:
            Id of the inserted row.
        """
        sql = 'INSERT INTO {} ("{}") VALUES ({})'.format(
            table, '", "'.join(kw), ', '.join(f':{col}' for col in kw))
        if id_column:
            sql += 'RETURNING "{}"'.format(id_column)
            return int(self._exec(sql, **kw).first()[0])
        self._exec(sql, **kw)
        return 0

    def _multi_insert(self,
                      table: str,
                      columns: typing.Sequence[str],
                      rows: typing.Sequence[typing.Sequence[typing.Any]],
                      *,
                      returning: typing.Optional[typing.Sequence[str]] = None,
                      on_conflict: str = '') -> typing.Sequence[_Dict]:
        """Executes an INSERT statement adding multiple rows at once.

        Args:
            table: Table to insert rows into.
            columns: Names of columns to insert.
            rows: An iterable of rows to insert.  Each element must be
                a collection of the same length as columns count.  Values of
                each element correspond to columns at the same index.
            returning: If present, list of columns to return for each inserted
                row.
            id_columns: If non-empty, body of the ‘ON CONFLICT’ phrase of the
                query.'.
        """
        names = '", "'.join(columns)
        sql = ', '.join(':r{i}c' + str(i) for i in range(len(columns)))
        sql = ', '.join('(' + sql.format(i=i) + ')' for i in range(len(rows)))
        sql = f'INSERT INTO "{table}" ("{names}") VALUES {sql}'
        if on_conflict:
            sql = f'{sql} ON CONFLICT {on_conflict}'
        if returning:
            names = '", "'.join(returning)
            sql += f' RETURNING "{names}"'
        values = {
            f'r{rno}c{cno}': value for rno, row in enumerate(rows)
            for cno, value in enumerate(row)
        }

        result = self._exec(sql, **values)
        if returning:
            return tuple(self._to_dict(row) for row in result)
        return ()

    @classmethod
    def _to_dict(cls, row: _Row) -> typing.Dict[str, typing.Any]:
        """Converts an SQLAlchemy row into a dictionary."""
        return dict(zip(row.keys(), row))

    @classmethod
    def _blob_from_data(cls, data: typing.Union[str, bytes]) -> bytes:
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
        # If the data is already compressed than we have to at least add a gzip
        # header.  If we don’t do that, when we serve the file we’re going to
        # serve it decompressed.
        must_compress = data.startswith(b'\x1f\x8b')
        if must_compress or len(data) > 18:
            level = 0 if must_compress else 9
            compressed = gzip.compress(data, level)
            if must_compress or len(compressed) < len(data):
                return compressed
        return data

    @classmethod
    def _str_from_blob(cls, blob: typing.Union[None, bytes, memoryview]) -> str:
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
        if bytes(blob[:2]) == b'\x1f\x8b':
            blob = gzip.decompress(blob)
        return str(blob, 'utf-8', 'replace')
