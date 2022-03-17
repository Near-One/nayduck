#!/bin/sh

# usage:  ./setup-host.sh ( [--mocknet] --worker | --builder | --frontend )

set -eu

if [ "$(id -u)" != 0 ]; then
	echo "$0: must be run as super user" >&2
	exit 1
fi

basedir=$PWD

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
	mkdir -m 700 /datadrive
	chown nayduck:nayduck /datadrive
fi

sudo -u nayduck git config --global advice.detachedHead false

cd /home/nayduck
if [ -e "$basedir/setup.tar.gz" ]; then
	# shellcheck disable=SC2024
	sudo -u nayduck tar zvx <"$basedir/setup.tar.gz"
	rm -- "$basedir/setup.tar.gz"
else
	echo "$0: no setup.tar.xz; not initialising /home/nayduck"
fi

rm -rf nayduck
sudo -u nayduck git clone https://github.com/near/nayduck.git
sudo -u nayduck python3 -m pip install --user -U --no-warn-script-location pip
sudo -u nayduck python3 -m pip install --user -U --no-warn-script-location \
     -r nayduck/requirements.txt

if [ "$type" = frontend ]; then
	apt-get -y install nodejs npm postgresql-client
	(
		cd frontend
		sudo -u nayduck npm install
		sudo -u nayduck npm run build
	)
	# At the moment back end is configured to listen on port 5005 (because
	# it’s run as unprivileged user and I haven’t figured out yet how to
	# pass an open listening socket from systemd to Flask) which means that
	# to listen to have the front end available on port 80 a redirection is
	# necessary:
	#     dev=ens4
	#     iptables -A PREROUTING -t nat -i ${dev?} -p tcp --dport 80 -j REDIRECT --to-port 5005
	# This isn’t automated because the device name may potentially be
	# different on different machines so this needs to be done manually.
	# This also needs to be added as a service to systemd so it’s run on
	# each boot.
else
	curl https://sh.rustup.rs -sSf | sudo -u nayduck sh -s -- -y
	sudo -u nayduck .cargo/bin/rustup target add wasm32-unknown-unknown
	if $is_mocknet; then
		sudo -u nayduck .cargo/bin/cargo install cargo-fuzz
	fi
fi

service=$type
if [ "$type" = frontend ]; then
	service=ui
fi
cp -nvt /etc/systemd/system/ -- \
   "/home/nayduck/nayduck/systemd/nayduck-$service.service"
systemctl enable "nayduck-$service"
if [ "$type" = worker ]; then
	cp -nvt /etc/systemd/system -- \
	   "/home/nayduck/nayduck/system/nayduck-fuzzer.service"
	systemctl enable "nayduck-fuzzer"
fi

rm -- "$basedir/setup-host.sh"

/sbin/reboot
