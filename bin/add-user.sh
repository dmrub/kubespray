#!/bin/bash

script() {
    local username=$1
    local user_groups=$2
    local password=$3

    local tool
    for tool in useradd groupadd getent usermod; do
        if ! type -f "$tool" > /dev/null 2>&1; then
            echo >&2 "No $tool tool found"
            exit 1
        fi
    done

    if ! getent passwd "$username"; then
        # Create user
        if useradd -m "$username"; then
            if [ -n "$password" ]; then
                # Set password
                passwd --stdin "$username" <<<"$password"
            fi
        fi
    fi

    if ! getent passwd "$username" >/dev/null; then
        echo >&2 "Could not create user $username"
        exit 1
    fi

    user_groups=${user_groups//,/ }

    local grp
    for grp in $user_groups; do
        echo "Add user $username to group $grp"
        if ! getent group "$grp" >/dev/null; then
            groupadd "$grp" || {
                echo >&2 "Could not create group $grp"
                exit 1
            }
        fi
        usermod -a -G "$grp" "$username" || {
            echo >&2 "Could not add $username user to $grp group"
            exit 1
        }
    done
}

if [ "$1" != "--remote" ]; then
    THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

    source "$THIS_DIR/init-env.sh"

    usage() {
        echo "Add user"
        echo
        echo "$0 [options] user-name [password]"
        echo "options:"
        echo "  -p, --host-pattern=        Ansible host pattern"
        echo "  -g, --groups               Groups separated by comma"
        echo "      --help                 Display this help and exit"
        echo "      --                     End of options"
    }

    HOST_PATTERN=all
    USER_GROUPS=

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
            -g|--groups)
                USER_GROUPS="${USER_GROUPS},$2"
                shift 2
                ;;
            --groups=*)
                USER_GROUPS="${USER_GROUPS},${1#*=}"
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
        USERNAME=$1
        shift
    else
        fatal "No username specified"
    fi

    if [ -n "$1" ]; then
        PASSWORD=$1
        shift
    else
        echo "No password specified, password will be not set"
    fi

    USER_GROUPS=${USER_GROUPS// /,}

    echo "Add user $USERNAME to $USER_GROUPS groups"
    if [ -n "$PASSWORD" ]; then
        echo "And set password"
    fi

    THIS_SCRIPT="$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )"

    run-ansible \
            "$HOST_PATTERN" \
            --become \
            -m script \
            --args "$THIS_SCRIPT --remote '$USERNAME' '$USER_GROUPS' '$PASSWORD'"

else
    # Remote code
    shift
    script "$@"
fi
