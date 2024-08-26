#!/bin/sh

# Start by creating a `setup.tar.gz` consisting of credentials from an existing
# NayDuck machine.  Let’s call that _source machine_.  To create the file,
# *locally* execute:
#
#     local$ ssh source sudo -u nayduck tar cC ~nayduck .nayduck .ssh | gzip -9 >/tmp/setup.tar.gz
#
# With the file ready, copy it together with this setup-host.sh script to the
# target machine which needs to be set up.  To do this (again locally) execute:
#
#     local$ scp /tmp/setup.tar.gz automation/setup-host.sh target:
#
# Once copying succeeds, log onto the target machine and execute the script
# there.  Again, ssh and execution of the command can be combined into the
# following single invocation on local machine:
#
#     local$ ssh target sudo /bin/sh setup-host.sh "--<role>"
#
# where --<role> is one of: --worker, --builder or --frontend.  The script will
# reboot the machine so you will be forcefully logged out.
#
# Copying and executing the script can be repeated on other machines that need
# to be set up.  Once all hosts are correctly initialised, cleanup the setup
# file:
#
#     local$ rm /tmp/setup.tar.gz

set -eu

if [ "$(id -u)" != 0 ]; then
	echo "$0: must be run as super user" >&2
	exit 1
fi

basedir=$PWD

type=
for arg; do
	case $arg in
	--worker|--builder|--frontend)
		if [ -n "$type" ]; then
			echo "$0: argument can be given only once: $arg" >&2
			exit 1
		fi
		type=${arg#--}
		;;
	*)
		echo "$0: unknown argument: $arg" >&2
		exit 1
	esac
done

if [ -z "$type" ]; then
	echo "$0: missing --worker, --builder or --frontend argument">&2
	exit 1
fi

set -x

apt-get -y update
apt-get -y upgrade
apt-get -y install fdisk git python3-pip libpq-dev lld libclang-dev

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
	# At the moment back end is configured to listen on port 4040 (because
	# it’s run as unprivileged user and I haven’t figured out yet how to
	# pass an open listening socket from systemd to Flask) which means that
	# to listen to have the front end available on port 80 a redirection is
	# necessary:
	#     dev=ens4
	#     iptables -A PREROUTING -t nat -i ${dev?} -p tcp --dport 80 -j REDIRECT --to-port 4040
	# This isn’t automated because the device name may potentially be
	# different on different machines so this needs to be done manually.
	# This also needs to be added as a service to systemd so it’s run on
	# each boot.
elif [ "$type" = worker ]; then
	apt-get -y install docker.io
	usermod -aGdocker nayduck
fi

case $type in
frontend) services=ui                        ;;
worker)   services='local-ssd worker fuzzer' ;;
*)        services=$type
esac
for service in $services; do
    cp -nvt /etc/systemd/system/ -- \
		"/home/nayduck/nayduck/systemd/nayduck-$service.service"
    systemctl enable "nayduck-$service"
done

rm -- "$basedir/setup-host.sh"

/sbin/reboot
