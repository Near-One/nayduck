--                                      -*- mode: sql sql-dialect: postgres; -*-

CREATE TYPE "build_status"
    AS ENUM('PENDING', 'BUILDING', 'BUILD DONE', 'BUILD FAILED', 'SKIPPED');
CREATE TYPE "test_status"
    AS ENUM('FAILED', 'CHECKOUT FAILED', 'SCP FAILED', 'TIMEOUT', 'PASSED',
            'IGNORED', 'CANCELED', 'RUNNING', 'PENDING');
CREATE TYPE "test_category"
    AS ENUM('pytest', 'mocknet', 'expensive');

DROP TABLE IF EXISTS "logs";
DROP TABLE IF EXISTS "tests";
DROP TABLE IF EXISTS "builds";
DROP TABLE IF EXISTS "runs";

CREATE TABLE "runs" (
  "run_id"      integer         NOT NULL GENERATED BY DEFAULT AS IDENTITY,
  "branch"      varchar         NOT NULL,
  "sha"         bytea           NOT NULL,
  "timestamp"   timestamptz     NOT NULL DEFAULT now(),
  "title"       varchar         NOT NULL,
  "requester"   varchar         NOT NULL,
  PRIMARY KEY ("run_id")
);
-- Used by UIDB.last_nightly_run
CREATE INDEX ON "runs" ("timestamp") WHERE "requester" = 'NayDuck';

CREATE TABLE "builds" (
  "build_id"    integer         NOT NULL GENERATED BY DEFAULT AS IDENTITY,
  "run_id"      integer         NOT NULL
                                REFERENCES "runs" ("run_id") ON DELETE CASCADE,
  "status"      "build_status"  NOT NULL,
  "started"     timestamptz,
  "finished"    timestamptz,
  "stderr"      bytea           NOT NULL DEFAULT ''::bytea,
  "stdout"      bytea           NOT NULL DEFAULT ''::bytea,
  "features"    varchar         NOT NULL DEFAULT '',
  "is_release"  boolean         NOT NULL DEFAULT FALSE,
  -- This is effectively denormalised duplicate of runs.requester == 'NayDuck'.
  "low_priority" boolean        NOT NULL DEFAULT 0,
  "builder_ip"  integer         NOT NULL DEFAULT 0,
  PRIMARY KEY ("build_id")
);
-- Used by MasterDB.get_new_build
CREATE INDEX ON "builds" ("low_priority", "build_id") WHERE status = 'PENDING';
-- Used by WorkerDB.get_pending_test
CREATE INDEX ON "builds" ("build_id")
 WHERE "status" = 'SKIPPED' OR ("status" = 'BUILD DONE' AND "builder_ip" != 0);
CREATE INDEX ON "builds" ("run_id");
CREATE INDEX ON "builds" ("builder_ip") WHERE builder_ip != 0;

CREATE TABLE "tests" (
  "test_id"     integer         NOT NULL GENERATED BY DEFAULT AS IDENTITY,
  "run_id"      integer         NOT NULL REFERENCES "runs" ("run_id")
                                                    ON DELETE CASCADE,
  "build_id"    integer         NOT NULL REFERENCES "builds" ("build_id")
                                                    ON DELETE CASCADE,
  "status"      "test_status"   NOT NULL DEFAULT 'PENDING',
  "category"    "test_category" NOT NULL,
  "name"        varchar         NOT NULL,
  "timeout"     integer         NOT NULL,
  "started"     timestamptz,
  "finished"    timestamptz,
  "worker_ip"   integer         NOT NULL DEFAULT 0,
  -- Denormalised duplicate of runs.branch to speed up history search queries.
  "branch"      varchar         NOT NULL,
  -- Denormalised duplicate of runs.requester == 'NayDuck'.
  "is_nightly"  boolean         NOT NULL,
  PRIMARY KEY ("test_id")
);
CREATE INDEX ON "tests" ("run_id");
-- Used by BackendDB.get_test_history and BackendDB.get_full_test_history
CREATE INDEX ON "tests" ("branch", "name", "test_id", "status");
-- Used by BackendDB.__get_last_test_success_timestamp
CREATE INDEX ON "tests" ("name", "finished")
 WHERE "is_nightly"
   AND finished IS NOT NULL
   AND status NOT IN ('PENDING', 'RUNNING');
-- Used by WorkerDB.get_pending_test
CREATE INDEX ON "tests" ("build_id", ("category" != 'mocknet'))
 WHERE "status" = 'PENDING';
-- Used by MasterDB.update_build_status (in the success=False case)
-- and by MasterDB.builds_without_pending_tests
CREATE INDEX ON "tests" ("build_id", "status")
 WHERE "status" IN ('PENDING', 'RUNNING');
-- Used by MasterDB.get_new_build
CREATE INDEX ON "tests" ("build_id")
 WHERE "status" = 'PENDING' AND "category" = 'expensive';

CREATE OR REPLACE VIEW "tests_history" (name, branch, status, count)
AS SELECT name, branch, status, count(*)
     FROM tests AS t
     JOIN (SELECT status
             FROM tests
            WHERE t.name = tests.name AND t.branch = tests.branch
            ORDER BY test_id
            LIMIT 30) AS statuses USING (name, branch)
    GROUP BY 1, 2, 3;

CREATE TABLE "logs" (
  "test_id"     integer         NOT NULL REFERENCES "tests" ("test_id")
                                                    ON DELETE CASCADE,
  "type"        varchar         NOT NULL,
  "log"         bytea           NOT NULL,
  "size"        bigint          NOT NULL,
  "storage"     varchar         NOT NULL,
  "stack_trace" boolean         NOT NULL,
  PRIMARY KEY ("test_id", "type")
);

-- SELECT SETVAL('runs_run_id_seq', MAX(run_id)) FROM runs;
-- SELECT SETVAL('builds_build_id_seq', MAX(build_id)) FROM builds;
-- SELECT SETVAL('tests_test_id_seq', MAX(test_id)) FROM tests;

DROP TABLE IF EXISTS "auth_cookies";
CREATE TABLE "auth_cookies" (
  "timestamp"   integer         NOT NULL,
  "cookie"      bigint          NOT NULL,
  PRIMARY KEY ("timestamp", "cookie")
);
