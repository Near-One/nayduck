#!/bin/sh

set -eux

dev=/dev/nvme0n1
dir=/datadrive

# Sanity checks
if ! [ -e "$dev" ]; then
	echo "$dev: device does not exist; nothing to do"
	exit 0
fi

if ! [ -e "${dev}p1" ]; then
	# Partition the disk:
	# - p1 → data partition, will become /datadrive
	# - p2 → swap partition
	sfdisk "$dev" <<EOF
		size=360G
		type=swap
		write
EOF

	# Data on the device is essentially lost on reboot and we’re treating it
	# as ephemeral.  There’s no point in keeping journal.
	mkfs.ext4 -E discard -O ^has_journal "${dev}p1"
	mkdir -p "$dir"
	mount "${dev}p1" "$dir" -o discard,noatime,nobarrier
	chown nayduck:nayduck "$dir"
else
	mount "${dev}p1" "$dir" -o discard,noatime,nobarrier
fi

# Enable swap on the second partition
mkswap "${dev}p2"
swapon "${dev}p2"

if ! [ -f "$dir/README" ]; then
	cat >$dir/README <<EOF
Data in this directory is ephemeral and may disappear on reboots.
Don’t keep any data which cannot be recreated here.
EOF
	chmod 444 "$dir/README"
fi

if ! [ -d "$dir/home" ]; then
	# Install Rustup and Cargo in /datadrive/home for NayDuck to use.  Those
	# always take a lot of space so best keep them on our massive local SSD.
	mkdir -p "$dir/home"
	chown nayduck:nayduck "$dir/home"
	sudo -u nayduck CARGO_HOME="$dir/home/cargo" RUSTUP_HOME="$dir/home/rustup" sh -c '
		set -eux
		curl https://sh.rustup.rs -sSf | sh -s -- -y
		"$CARGO_HOME/bin/rustup" target add wasm32-unknown-unknown
		"$CARGO_HOME/bin/cargo" install cargo-fuzz
	'
fi

if ! [ -d "$dir/docker" ]; then
	# Configure Docker to store its stuff in /datadrive since otherwise
	# root file-system would quickly run out of space.
	if -d [ /var/lib/docker ]; then
		mv -f -- /var/lib/docker "$dir/docker"
	fi
	printf '{"data-root":"%s/docker"}' "$dir" >/etc/docker/daemon.json
fi
