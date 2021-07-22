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

    def update_run_status(self, build_id: int, success: bool, *,
                          out: bytes, err: bytes) -> None:
        status = 'BUILD DONE' if success else 'BUILD FAILED'
        sql = "UPDATE builds SET finished = now(), status = %s, stderr=%s, stdout = %s WHERE build_id=%s"
        self._execute_sql(sql, (status, err, out, build_id))
        if not success:
            sql = "UPDATE tests SET status = 'CANCELED' WHERE build_id=%s and status='PENDING'"
            self._execute_sql(sql, (build_id,))

    def handle_restart(self, ip_address):
        sql = "UPDATE builds SET started = null, status = 'PENDING', ip=null  WHERE status = 'BUILDING' and ip=%s"
        self._execute_sql(sql, (ip_address,))

    def get_builds_with_finished_tests(self, ip_address):
        sql = "SELECT build_id FROM builds WHERE ip=%s ORDER BY build_id desc LIMIT 20"
        result = self._execute_sql(sql, (ip_address,))
        builds = result.fetchall()
        finished_runs = []
        for build in builds:
            sql = "SELECT count(IF(status='PENDING' or status='RUNNING',1,NULL)) AS still_going FROM tests WHERE build_id = %s"
            result = self._execute_sql(sql, (build['build_id'],))
            going = result.fetchone()
            if going['still_going'] == 0:
                finished_runs.append(build['build_id'])
        return finished_runs

       