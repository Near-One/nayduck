import typing

from lib import common_db


class MasterDB(common_db.DB):

    def __init__(self, ipv4: int) -> None:
        """Initialises the connection.

        Args:
            ipv4: IP address of the master (as an integer).  This will be stored
                in a database when marking builds "owned" by the master and also
                used to query builds "owned" by the master.
        """
        super().__init__()
        self._ipv4 = ipv4

    def get_new_build(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Returns a pending build to process or None if none found."""
        return self._with_transaction(self.__get_new_build)

    def __get_new_build(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Implementation of get_new_build method (which see).

        This method must be run inside of a transaction because it uses
        variables and so we cannot tolerate disconnects between the two queries.
        """
        sql = '''UPDATE builds
                    SET started = NOW(),
                        status = 'BUILDING',
                        master_ip = %s,
                        build_id = (@build_id := build_id)
                  WHERE status = 'PENDING'
                  ORDER BY priority, build_id
                  LIMIT 1'''
        result = self._exec(sql, self._ipv4)
        if result.rowcount == 0:
            return None
        # We're executing this query once in a blue moon so it doesn't need to
        # be super optimised.  If we cared about the performance we could
        # duplicate `sha` column in a build and add `has_expensive` column, but
        # in this instance we care more about database normalisation.
        sql = '''SELECT b.build_id,
                        r.sha,
                        b.features,
                        b.is_release,
                        SUM(t.category = "expensive") != 0 AS expensive
                   FROM builds b
                   JOIN runs r ON (r.id = b.run_id)
                   JOIN tests t USING (build_id)
                  WHERE b.build_id = @build_id
                  LIMIT 1'''
        row = self._exec(sql).fetchone()
        return row

    def update_build_status(self, build_id: int, success: bool, *, out: bytes,
                            err: bytes) -> None:
        """Updates build status in the database.

        If the build failed also updates all dependent tests to CANCELED status.

        Args:
            build_id: Id of the build.
            success: Whether the build has succeeded.
            out: Standard output of the build process.
            err: Standard error output of the build process.
        """
        if success:
            sql = '''UPDATE builds
                        SET finished = NOW(),
                            status = "BUILD DONE",
                            stderr = %s,
                            stdout = %s
                      WHERE build_id = %s'''
        else:
            sql = '''UPDATE builds JOIN tests USING (build_id)
                        SET builds.finished = NOW(),
                            builds.status = "BUILD FAILED",
                            builds.stderr = %s,
                            builds.stdout = %s,
                            tests.status = "CANCELED"
                      WHERE builds.build_id = %s
                        AND tests.status = "PENDING"'''
        out = self._blob_from_data(out)
        err = self._blob_from_data(err)
        self._exec(sql, err, out, build_id)

    def handle_restart(self) -> None:
        sql = '''UPDATE builds
                    SET started = null,
                        status = 'PENDING',
                        master_ip = 0
                  WHERE status = 'BUILDING'
                    AND master_ip = %s'''
        self._exec(sql, self._ipv4)

    def builds_without_pending_tests(self) -> typing.Sequence[int]:
        """Returns IDs of builds assigned to this master w/no pending tests."""
        sql = '''SELECT build_id
                   FROM builds LEFT JOIN tests USING (build_id)
                  WHERE master_ip = %s
                  GROUP BY 1
                 HAVING SUM(tests.status IN ('PENDING', 'RUNNING')) = 0'''
        result = self._exec(sql, self._ipv4)
        return tuple(int(build['build_id']) for build in result.fetchall())

    def unassign_builds(self, ids: typing.Sequence[int]) -> None:
        """Unassigns given builds from any master."""
        sql = 'UPDATE builds SET master_ip = 0 WHERE build_id IN ({})'
        self._exec(sql.format(', '.join(str(int(bid)) for bid in ids)))
