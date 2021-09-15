import typing

from lib import common_db


class Test:
    test_id: int
    build_id: int
    name: str
    builder_ip: int
    sha: str


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

    def get_pending_test(self, include_mocknet: bool) -> typing.Optional[Test]:
        """Returns a pending test to process or None if none found.

        Args:
            include_mocknet: Whether to consider mocknet tests in the result.
        Returns:
            A build to process or None if none are present.
        """
        return self._in_transaction(self.__get_pending_test, include_mocknet)

    def __get_pending_test(self, mocknet: bool) -> typing.Optional[Test]:
        """Implementation of get_pending_test method (which see).

        This method must be run inside of a transaction because it uses
        variables and so we cannot tolerate disconnects between the two queries.
        """
        sql = '''UPDATE tests
                    SET started = NOW(),
                        finished = NULL,
                        status = 'RUNNING',
                        worker_ip = :ip,
                        test_id = (@test_id := test_id)
                  WHERE status = 'PENDING'
                    AND build_id IN (SELECT build_id
                                       FROM builds
                                      WHERE status IN ('BUILD DONE', 'SKIPPED'))
                    {where}
                  ORDER BY {order_by} priority, test_id
                  LIMIT 1'''.format(
            where='' if mocknet else 'AND category != "mocknet"',
            order_by='category != "mocknet", ' if mocknet else '')
        res = self._exec(sql, ip=self._ipv4)
        if res.rowcount == 0:
            return None
        sql = '''SELECT t.test_id, t.build_id, t.name, b.builder_ip, r.sha
                   FROM tests t
                   JOIN runs r ON (r.id = t.run_id)
                   JOIN builds b USING (build_id)
                  WHERE t.test_id = @test_id
                  LIMIT 1'''
        return typing.cast(typing.Optional[Test], self._exec(sql).first())

    def test_started(self, test_id: int) -> None:
        sql = 'UPDATE tests SET started = NOW() WHERE test_id = :id'
        self._exec(sql, id=test_id)

    def update_test_status(self, status: str, test_id: int) -> None:
        sql = '''UPDATE tests
                    SET finished = NOW(), status = :status
                  WHERE test_id = :id'''
        self._exec(sql, status=status, id=test_id)

    def save_short_logs(self, test_id: int,
                        logs: typing.Collection[typing.Any]) -> None:
        columns = ('test_id', 'type', 'size', 'log', 'storage', 'stack_trace')
        self._multi_insert(
            'logs',
            columns,
            [(test_id, log.name, log.size, self._blob_from_data(
                log.data or b''), log.url or '', log.stack_trace)
             for log in logs],
            replace=True)

    def handle_restart(self) -> None:
        sql = '''UPDATE tests
                    SET started = NULL, status = 'PENDING', worker_ip = 0
                  WHERE status = 'RUNNING' AND worker_ip = :ip'''
        self._exec(sql, ip=self._ipv4)
