import mysql.connector
import random

import datetime
import os
import sys
import typing

sys.path.append(os.path.abspath('../main_db'))
import common_db

class MasterDB (common_db.DB):
    def get_new_build(
            self, ip_address: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Returns a pending build to process or None if none found.

        Args:
            ip_address: IP address of the master making the request.  This will
                be stored in the database so workers will know where to find
                build artefacts.
        Returns:
            A build to process or None if none are present.
        """
        return self._with_transaction(lambda: self.__get_new_build(ip_address))

    def __get_new_build(
            self, ip_address: str
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """Implementation of get_new_build method (which see).

        This method must be run inside of a transaction because it uses
        variables and so we cannot tolerate disconnects between the two queries.
        """
        sql = '''UPDATE builds
                    SET started = NOW(),
                        status = 'BUILDING',
                        ip = %s,
                        build_id = (@build_id := build_id)
                    WHERE status = 'PENDING'
                    ORDER BY priority, build_id
                    LIMIT 1'''
        result = self._execute_sql(sql, (ip_address,))
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
                        SUM(t.name LIKE "%expensive %") AS expensive
                   FROM builds b
                   JOIN runs r ON (r.id = b.run_id)
                   JOIN tests t USING (build_id)
                  WHERE b.build_id = @build_id
                  LIMIT 1'''
        row = self._execute_sql(sql).fetchone()
        row['expensive'] = bool(row['expensive'])
        return row

    def update_build_status(self, build_id: int, success: bool, *,
                            out: bytes, err: bytes) -> None:
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
        self._execute_sql(sql, (err, out, build_id))

    def handle_restart(self, ip_address):
        sql = "UPDATE builds SET started = null, status = 'PENDING', ip=null  WHERE status = 'BUILDING' and ip=%s"
        self._execute_sql(sql, (ip_address,))


    def with_builds_without_pending_tests(
            self,
            ip_address: str,
            callback: typing.Callable[[typing.Iterable[int]], typing.Any]
    ) -> None:
        """Runs cleanup callback on IDs of builds with no unfinished tests.

        Retrieves IDs of all builds assigned to this master which no pending
        test depends on, calls callback on that list and then marks those builds
        as no longer available.

        Args:
            ip_address: IP of the master.
            callback: Callback to call with sequence of build IDs to cleanup.
        """
        sql = '''SELECT build_id
                   FROM builds JOIN tests USING (build_id)
                  WHERE ip = %s
                    AND tests.status NOT IN ('PENDING', 'RUNNING')
                  GROUP BY 1'''
        result = self._execute_sql(sql, (ip_address,))
        builds = tuple(int(build['build_id']) for build in result.fetchall())
        if builds:
            CALLBACK(builds)
            sql = 'UPDATE builds SET ip = NULL WHERE build_id IN ({})'
            sql = sql.format(', '.join(str(build_id) for build_id in builds))
            self._execute_sql(sql)
