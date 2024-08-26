import typing

from lib import common_db


class Build:
    build_id: int
    features: str
    is_release: int
    sha: str
    expensive: bool


class BuilderDB(common_db.DB):

    def __init__(self, ipv4: int) -> None:
        """Initialises the connection.

        Args:
            ipv4: IP address of the builder (as an integer).  This will be
                stored in a database when marking builds "owned" by the builder
                and also used to query builds "owned" by the builder.
        """
        super().__init__()
        self._ipv4 = ipv4

    def get_new_build(self) -> typing.Optional[Build]:
        """Returns a pending build to process or None if none found."""
        build_sql = '''SELECT build_id
                         FROM builds
                        WHERE status = 'PENDING'
                        ORDER BY low_priority, build_id
                        LIMIT 1
                          FOR UPDATE'''
        update_sql = f'''UPDATE builds
                            SET started = NOW(),
                                finished = NULL,
                                status = 'BUILDING',
                                builder_ip = {int(self._ipv4)}
                          WHERE build_id IN ({build_sql})
                      RETURNING build_id, run_id, features, is_release'''
        expensive_tests_sql = '''SELECT test_id FROM tests
                                  WHERE status = 'PENDING'
                                    AND category = 'expensive'
                                    AND build_id = build.build_id'''
        sql = f'''WITH build AS ({update_sql})
                  SELECT build_id, features, is_release,
                         ENCODE(sha, 'hex') sha,
                         EXISTS ({expensive_tests_sql}) expensive
                    FROM build JOIN runs USING (run_id)'''
        return typing.cast(typing.Optional[Build], self._exec(sql).first())

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
        sql = '''UPDATE builds
                    SET finished = NOW(),
                        status = :status,
                        stderr = :err,
                        stdout = :out
                  WHERE build_id = :id'''
        if success:
            status = 'BUILD DONE'
        else:
            status = 'BUILD FAILED'
            sql = f'''
                WITH b AS ({sql} RETURNING build_id)
                UPDATE tests SET status = 'CANCELED'
                 WHERE build_id IN (SELECT build_id FROM b)
                   AND tests.status = 'PENDING'
            '''
        out = self._blob_from_data(out)
        err = self._blob_from_data(err)
        self._exec(sql, status=status, err=err, out=out, id=build_id)

    def handle_restart(self) -> None:
        sql = '''UPDATE builds
                    SET started = NULL,
                        status = 'PENDING',
                        builder_ip = 0
                  WHERE status = 'BUILDING'
                    AND builder_ip = :ip'''
        self._exec(sql, ip=self._ipv4)

    def builds_without_pending_tests(self) -> typing.Sequence[int]:
        """Returns IDs of builds assigned to this builder w/no pending tests."""
        sql = '''SELECT builds.build_id
                   FROM builds
                   LEFT JOIN tests ON (tests.build_id = builds.build_id
                                   AND tests.status IN ('RUNNING', 'PENDING'))
                  WHERE builder_ip = :ip AND test_id IS NULL'''
        scalars = self._exec(sql, ip=self._ipv4).scalars()
        return tuple(int(bid) for bid in scalars)

    def unassign_builds(self, ids: typing.Sequence[int]) -> None:
        """Unassigns given builds from any builder."""
        sql = 'UPDATE builds SET builder_ip = 0 WHERE build_id IN ({})'
        self._exec(sql.format(', '.join(str(int(bid)) for bid in ids)))

    def get_latest_successful_build(self) -> typing.Optional[Build]:
        """Returns the latest successful build if available."""
        sql = '''SELECT * FROM builds
                WHERE status = 'BUILD DONE'
                AND finished > NOW() - INTERVAL '1 hour'
                ORDER BY finished DESC
                LIMIT 1'''
        return self._fetch_one(sql)