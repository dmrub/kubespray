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

    local OLD_SNAPSHOT="$1"
    local NEW_SNAPSHOT="$2"

    if [ -z "$OLD_SNAPSHOT" ]; then
        echo >&2 "No old snapshot name specified"
        exit 1
    fi

    if [ -z "$NEW_SNAPSHOT" ]; then
        echo >&2 "No new snapshot name specified"
        exit 1
    fi

    local mentry mentry_arr device mp uuid disk_mount_path \
          subvol_name snapshots_path old_snapshot_path new_snapshot_path

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

        subvol_name=$(btrfs subvolume show "$mp" | awk '/Name:/ { print $2 }')
        if [ -n "$subvol_name" ]; then
            echo "Subvolume name: $subvol_name"

            snapshots_path="${disk_mount_path}/snapshots/${subvol_name}"
            snapshots_path=$(readlink -f "$snapshots_path")
            old_snapshot_path=$snapshots_path/$OLD_SNAPSHOT
            new_snapshot_path=$snapshots_path/$NEW_SNAPSHOT

            if [ -d "$old_snapshot_path" ]; then

                if [ -d "$new_snapshot_path" ]; then
                    echo >&2 "Could not rename snapshot to $NEW_SNAPSHOT, directory $new_snapshot_path already exists"
                    exit 1
                fi

                echo "Rename snapshot $OLD_SNAPSHOT to $NEW_SNAPSHOT of path $mp (subvolume: $subvol_name) in $snapshot_path"

                btrfs subvolume snapshot -r "$old_snapshot_path" "$new_snapshot_path" || {
                    echo >&2 "Could not create snapshot of $old_snapshot_path in $new_snapshot_path"
                    exit 1
                }

                btrfs subvolume delete "$old_snapshot_path" || {
                    echo >&2 "Could not delete snapshot $old_snapshot_path of $mp"
                    exit 1
                }
            fi
        fi
    done
}

if [ "$1" != "--snapshot" ]; then
    THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

    source "$THIS_DIR/init-env.sh"

    usage() {
        echo "Rename btrfs snapshot"
        echo
        echo "$0 [options] old-snapshot-name new-snapshot-name"
        echo "options:"
        echo "  -p, --host-pattern=        Ansible host pattern"
        echo "      --help                 Display this help and exit"
        echo "      --                     End of options"
    }

    HOST_PATTERN=all
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

    if [ -z "$1" ]; then
        fatal "No old snapshot name specified"
    fi

    OLD_SNAPSHOT="$1"
    shift

    if [ -z "$1" ]; then
        fatal "No new snapshot name specified"
    fi

    NEW_SNAPSHOT="$1"
    shift

    echo "Rename snapshot $OLD_SNAPSHOT to $NEW_SNAPSHOT on hosts $HOST_PATTERN"

    ansible -i "$ANSIBLE_INVENTORY" "$HOST_PATTERN" --become -m script --args "'$0' --snapshot '$OLD_SNAPSHOT' '$NEW_SNAPSHOT'"

else
    # Remote code
    shift
    script "$@"
fi
