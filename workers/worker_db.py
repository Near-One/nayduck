import typing

from lib import common_db


class Test:
    test_id: int
    build_id: int
    name: str
    timeout: int
    skip_build: bool
    builder_ip: int
    sha: str
    tries: int


class WorkerDB(common_db.DB):

    def __init__(self, ipv4: int) -> None:
        """Initialises the connection.

        Args:
            ipv4: IP address of the worker (as an integer).  This will be stored
                in a database when marking tests "owned" by the worker and also
                used to query tests "owned" by the worker.
        """
        super().__init__()
        self._ipv4 = ipv4

    def get_pending_test(self) -> typing.Optional[Test]:
        """Returns a pending test to process or None if none found."""
        sql = '''SELECT test_id
                   FROM tests
                   JOIN builds USING (build_id)
                  WHERE tests.status = 'PENDING'
                    AND (skip_build OR
                         (builds.status = 'BUILD DONE' AND builder_ip != 0))
                  ORDER BY low_priority
                  LIMIT 1'''
        sql = f'''UPDATE tests
                     SET started = NOW(),
                         finished = NULL,
                         status = 'RUNNING',
                         worker_ip = :ip,
                         tries = tries + 1
                   WHERE test_id IN ({sql})
               RETURNING test_id, build_id, run_id, name, timeout, skip_build,
                         tries'''
        sql = f'''WITH test AS ({sql})
                  SELECT test_id, build_id, name, timeout, skip_build,
                         builder_ip, ENCODE(sha, 'hex') AS sha, tries
                    FROM test
                    JOIN runs USING (run_id)
                    JOIN builds USING (build_id)'''
        row = self._exec(sql, ip=self._ipv4).first()
        test = typing.cast(typing.Optional[Test], row)
        if test and test.tries > 1:
            self._exec('DELETE FROM logs WHERE test_id = :id', id=test.test_id)
        return test

    def test_started(self, test_id: int) -> None:
        sql = '''UPDATE tests
                    SET started = NOW(), finished = NULL
                  WHERE test_id = :id'''
        self._exec(sql, id=test_id)

    def update_test_status(self, test_id: int, status: str) -> None:
        sql = '''UPDATE tests
                    SET finished = NOW(), status = :status
                  WHERE test_id = :id'''
        self._exec(sql, status=status, id=test_id)

    def retry_test(self, test_id: int) -> None:
        sql = '''UPDATE tests
                    SET started = NULL, status = 'PENDING'
                  WHERE test_id = :id'''
        self._exec(sql, id=test_id)

    def save_short_logs(self, test_id: int,
                        logs: typing.Collection[typing.Any]) -> None:
        columns = ('test_id', 'type', 'size', 'log', 'storage', 'stack_trace')
        self._multi_insert(
            'logs',
            columns,
            [(test_id, log.name, log.size, self._blob_from_data(
                log.data or b''), log.url or '', log.stack_trace)
             for log in logs],
            on_conflict=('(test_id, type) DO UPDATE'
                         ' SET size = excluded.size, log = excluded.log,'
                         '     storage = excluded.storage,'
                         '     stack_trace = excluded.stack_trace'))

    def handle_restart(self) -> None:
        sql = '''UPDATE tests
                    SET started = NULL,
                        status = 'PENDING',
                        worker_ip = 0,
                        tries = GREATEST(tries - 1, 0)
                  WHERE status = 'RUNNING' AND worker_ip = :ip'''
        self._exec(sql, ip=self._ipv4)
