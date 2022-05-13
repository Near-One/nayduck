# A bit of a hacky script for running all the checks and formatting for the code
# base.

set -eu

parallel 'sh -xc {}' ::: \
	'exec pylint -j0 */*.py' \
	'exec python -m yapf -pir .' \
	'exec mypy -m backend.backend' \
	'exec mypy -m fuzzers.main' \
	'exec mypy -m workers.builder' \
	'exec mypy -m workers.worker' \
	'exec shellcheck */*.sh'

exec pytest "$@"
