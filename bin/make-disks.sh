#!/bin/bash

TMP_DIR=

cleanup() {
    if [ -d "$TMP_DIR" ]; then
        umount "$TMP_DIR"
        rmdir "$TMP_DIR"
        TMP_DIR=
    fi
}

uuid-of() {
    blkid -o value -s UUID "$1"
}

add-filesystem() {
    local mp=$2

    mkdir -p "$mp" || return 1

    if ! awk -v mp="$mp" 'BEGIN { found=0; } /^($|[[:space:]]*#)/ { next; } $2 == mp { found=1; exit 0; } END { if (!found) exit 1; }' /etc/fstab; then
        printf '%s\n' "$*" >> /etc/fstab
    fi
    mount "$mp" || return 1
    return 0
}

script() {
    echo "Running on $(hostname)"
    shift # Drop --script

    DEV=$1
    PARTDEV=$2
    shift 2

    echo "Create partition $PARTDEV on device $DEV"

    if [[ ! -b "$DEV" ]]; then
        echo "Device $DEV does not exist"
        exit 1
    fi

    if [[ -b "$DEV" && ! -b "$PARTDEV" ]]; then
        echo "Partition $PARTDEV does not exist, creating ..."
        set -xe
        parted -s -a optimal "$DEV" mklabel gpt mkpart primary btrfs 0% 100%
        partprobe
        mkfs.btrfs -f "$PARTDEV"
        set +xe
    fi

    local FSTYPE=$(blkid -o value -s TYPE "$PARTDEV")

    if [[ -b "$PARTDEV" && "$FSTYPE" != "btrfs" ]]; then
        echo "Make filesystem in partition $PARTDEV"
        mkfs.btrfs "$PARTDEV"
    fi

    trap cleanup SIGINT SIGTERM EXIT

    TMP_DIR=$(mktemp -d)
    echo "Mount btrfs to $TMP_DIR"
    mount -t btrfs "$PARTDEV" "$TMP_DIR" || exit 1

    local UUID
    UUID=$(blkid -o value -s UUID "$PARTDEV") || exit 1

    set -x
    btrfs subvolume list "$TMP_DIR"
    set +x

    local dir
    for dir in root docker; do
        if [[ ! -e "$TMP_DIR/$dir" ]]; then
            echo "Create subvolume $TMP_DIR/$dir"
            btrfs subvolume create "$TMP_DIR/$dir" || exit 1
        fi
    done

    add-filesystem UUID=$UUID /storage btrfs defaults,subvol=root,nofail 0 2
    add-filesystem UUID=$UUID /var/lib/docker btrfs defaults,subvol=docker,nofail 0 2
    mount -a
}

if [[ "$1" != "--script" ]]; then
    THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

    source "$THIS_DIR/init-env.sh"

    DEV=/dev/sdb
    PARTDEV=/dev/sdb1

    usage() {
        echo "Make disks"
        echo
        echo "$0 [options]"
        echo "options:"
        echo "  -p, --host-pattern=        Ansible host pattern"
        echo "      --dev=                 Device (default: $DEV)"
        echo "      --part=                Partition (default: $PARTDEV)"
        echo "      --help                 Display this help and exit"
        echo "      --                     End of options"
    }

    HOST_PATTERN=all

    while [[ "$1" == "-"* ]]; do
        case "$1" in
            -p|--host-pattern)
                HOST_PATTERN="$2"
                shift 2
                ;;
            --host-pattern=*)
                HOST_PATTERN="${1#*=}"
                shift
                ;;
            --dev=*)
                DEV="${1#*=}"
                shift
                ;;
            --part=*)
                PART="${1#*=}"
                shift
                ;;
            --help)
                usage
                exit
                ;;
            --)
                shift
                break
                ;;
            -*)
                fatal "Unknown option $1"
                ;;
            *)
            break
            ;;
        esac
    done

    THIS_SCRIPT="$(readlink -f "$BASH_SOURCE")"

    run-ansible \
        "$HOST_PATTERN" --become -m script --args "$THIS_SCRIPT --script $DEV $PARTDEV $@"

else
    # Remote code

    script "$@"
fi
