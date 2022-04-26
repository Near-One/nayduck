#!/bin/sh

set -eu

only_frontend=false
for arg; do
	case $arg in
	--frontend-only|--front-end-only)
		only_frontend=true
		;;
	*)
		echo "$0: unknown argument: $arg" >&2
		exit 1
	esac
done

services="$(systemctl list-unit-files -tservice --state=enabled 'nayduck-*' |
                sed -ne 's/\.service.*$//p')"

has_service() {
	echo "$services" | grep -Fq "$1"
}

has_ui=false
if has_service nayduck-ui; then
	has_ui=true
elif $only_frontend; then
	echo 'No front end running; nothing to do'
	exit 0
fi

sudo -u nayduck /bin/sh -c "
	set -eux
	cd ~/nayduck
	git remote update --prune
	git reset --hard origin/master
	if ! $only_frontend; then
		python3 -m pip install --no-warn-script-location -U pip
		python3 -m pip install --no-warn-script-location -U -r requirements.txt
	fi
	if $has_ui; then
		cd frontend
		npm install -U
		npm run build
	fi
"

if $only_frontend; then
	exit 0
fi

for service in nayduck-ui nayduck-builder nayduck-worker; do
	if has_service "$service"; then
		sudo systemctl restart "$service"
	fi
done
