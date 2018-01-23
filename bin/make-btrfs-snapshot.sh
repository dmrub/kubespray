#!/bin/bash

remove-mountpoint() {
    local mp=$1
    local tmpfile
    if [ -d "$mp" ]; then
        umount "$mp"
        rmdir "$mp"

        tmpfile=`mktemp -q -t fstab.XXXXXXXXXX` && {
            # Safe to use $tmpfile in this block
            awk -v mp="$mp" '/^($|[[:space:]]*#)/ { print $0; next; } $2 != mp { print $0; }' /etc/fstab > "$tmpfile" && \
                cat "$tmpfile" > /etc/fstab
            rm "$tmpfile"
        }
    fi
}

script() {
    local tool
    for tool in btrfs blkid; do
        if ! type -f "$tool" > /dev/null 2>&1; then
            echo >&2 "No $tool tool found"
            exit 1
        fi
    done

    local SNAPSHOT="$1"

    if [ -z "$SNAPSHOT" ]; then
        echo >&2 "No snapshot name specified"
        exit 1
    fi

    local mentry mentry_arr device mp uuid disk_mount_path \
          subvol_name snapshots_path snapshot_path

    for mentry in $(mount | awk '/type btrfs/ { print $1 ":" $3; }'); do
        IFS=":" mentry_arr=($mentry)
        device=${mentry_arr[0]}
        mp=${mentry_arr[1]}

        uuid=$(blkid -o value -s UUID "$device")

        disk_mount_path="/mnt/disk-${uuid}"
        mkdir -p "$disk_mount_path" || exit 1
        if ! grep -qF "$disk_mount_path" /etc/fstab; then
            echo "UUID=${uuid} ${disk_mount_path} btrfs   subvol=/ 0 0" >> /etc/fstab
            if ! mount | grep -qF "$disk_mount_path"; then
                mount "$disk_mount_path" || exit 1
            fi
        fi

        echo "BTRFS device: $device"
        echo "BTRFS mount point: $mp"
        echo "Blkid UUID: $uuid"
        btrfs subvolume show "$mp"

        subvol_name=$(btrfs subvolume show "$mp" | awk '/Name:/ { print $2 }')
        if [ -n "$subvol_name" ]; then
            echo "Subvolume name: $subvol_name"

            snapshots_path="${disk_mount_path}/snapshots/${subvol_name}"
            mkdir -p "$snapshots_path" || {
                echo >&2 "Could not create directory $snapshots_path"
                exit 1
            }
            snapshots_path=$(readlink -f "$snapshots_path")
            snapshot_path=$snapshots_path/$SNAPSHOT
            if [ ! -d "$snapshot_path" ]; then
                echo "Create $SNAPSHOT snapshot of path $mp (subvolume: $subvol_name) in $snapshot_path"

                btrfs subvolume snapshot -r "$mp" "$snapshot_path" || {
                    echo >&2 "Could not create snapshot of $mp in $snapshot_path"
                    exit 1
                }
            else
                echo "$SNAPSHOT snapshot of path $mp (subvolume: $subvol_name) already exists"
            fi
        fi
    done
}

if [ "$1" != "--snapshot" ]; then
    THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

    source "$THIS_DIR/init-env.sh"

    usage() {
        echo "Make btrfs snapshots"
        echo
        echo "$0 [options] [snapshot-name]"
        echo "options:"
        echo "  -p, --host-pattern=        Ansible host pattern"
        echo "      --help                 Display this help and exit"
        echo "  -t, --add-timestamp        Add timestamp to the snapshot name"
        echo "      --                     End of options"
        echo ""
        echo "Default snapshot name: $SNAPSHOT"
    }

    HOST_PATTERN=all
    SNAPSHOT=initial
    ADD_TIMESTAMP=

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
            -t|--add-timestamp)
                ADD_TIMESTAMP=true
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

    if [ -n "$1" ]; then
        SNAPSHOT="$1"
        shift
    fi

    if [ "$ADD_TIMESTAMP" = "true" ]; then
        SNAPSHOT=${SNAPSHOT}-$(date '+%Y-%m-%d-%H:%M')
    fi

    echo "Making snapshot $SNAPSHOT on hosts $HOST_PATTERN"

    THIS_SCRIPT="$(readlink -f "$BASH_SOURCE")"

    ansible -i "$ANSIBLE_INVENTORY" "$HOST_PATTERN" --become -m script --args "$THIS_SCRIPT --snapshot '$SNAPSHOT'"

else
    # Remote code
    shift
    script "$@"
fi

# btrfs subvolume snapshot -r / /snapshots/root/$(date '+%Y-%m-%d')
# btrfs subvolume delete /snapshots/root/2016-11-10
# btrfs filesystem df /
# btrfs filesystem usage /
