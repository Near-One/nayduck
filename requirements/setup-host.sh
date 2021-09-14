#!/bin/sh

# usage:  ./setup-host.sh ( [--mocknet] --worker | --builder | --frontend )

set -eu

if [ "$(id -u)" != 0 ]; then
	echo "$0: must be run as super user" >&2
	exit 1
fi

type=
is_mocknet=false
for arg; do
	case $arg in
	--worker|--builder|--frontend)
		if [ -n "$type" ]; then
			echo "$0: argument can be given only once: $arg" >&2
			exit 1
		fi
		type=${arg#--}
		;;
	--mocknet)
		is_mocknet=true
		;;
	*)
		echo "$0: unknown argument: $arg" >&2
		exit 1
	esac
done

if [ -z "$type" ]; then
	if $is_mocknet; then
		type=worker
	else
		echo "$0: missing --worker, --builder or --frontend argument">&2
		exit 1
	fi
elif [ "$type" != worker ] && $is_mocknet; then
	echo "$0: --mocknet argument is not compatible with --$type" >&2
	exit 1
fi

set -x

apt-get -y update
apt-get -y upgrade
apt-get -y install git python3-pip libpq-dev lld libclang-dev

grep -q ^nayduck: /etc/passwd ||
	adduser --disabled-login --gecos NayDuck nayduck
if ! [ -d /datadrive ]; then
	mkdir -m 700 -p /datadrive
	chown nayduck:nayduck /datadrive
fi

sudo -u nayduck git config --global advice.detachedHead false

cd /home/nayduck
rm -rf nayduck
sudo -u nayduck git clone https://github.com/near/nayduck.git
sudo -u nayduck python3 -m pip install --user -U --no-warn-script-location pip
sudo -u nayduck python3 -m pip install --user -U --no-warn-script-location \
     -r nayduck/requirements/requirements.txt

if [ "$type" = frontend ]; then
	apt-get -y install nodejs npm postgresql-client
	(
		cd frontend
		sudo -u nayduck npm install
		sudo -u nayduck npm run build
	)
	# dev=ens4
	# iptables -A PREROUTING -t nat -i ${dev?} -p tcp --dport 80 -j REDIRECT --to-port 5005
else
	curl https://sh.rustup.rs -sSf | sudo -u nayduck sh
	sudo -u nayduck .cargo/bin/rustup target add wasm32-unknown-unknown
	if $is_mocknet; then
		sudo -u nayduck .cargo/bin/cargo install cargo-fuzz
	fi
fi

service=$type
if [ "$type" = frontend ]; then
	serviec=ui
fi
cp -nvt /etc/systemd/system/ -- \
   "/home/nayduck/nayduck/systemd/nayduck-$service.service"
systemctl enable "nayduck-$service"

#/sbin/reboot
