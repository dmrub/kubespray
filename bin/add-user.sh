#!/usr/bin/env bash

set -eo pipefail

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P))

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

usage() {
    echo "Add user"
    echo
    echo "$0 [options] user-name [password]"
    echo "options:"
    echo "  -p, --host-pattern=          Ansible host pattern"
    echo "  -g, --groups=                Groups separated by comma"
    echo "  -f, --full-name=             Full user name (by default user name)"
    echo "  -a, --admin                  User is admin "
    echo "                               (e.g. wheel group on RedHat, sudo group on Ubuntu)"
    echo "  -k, --user-public-key-file=  User public key file"
    echo "      --echo                   Output ansible command to stderr (not output by default)"
    echo "      --help                   Display this help and exit"
    echo "      --                       End of options"
}

# https://www.linuxjournal.com/content/normalizing-path-names-bash

normpath() {
    # Remove all /./ sequences.
    local path=${1//\/.\//\/}

    # Remove dir/.. sequences.
    while [[ $path =~ ([^/][^/]*/\.\./) ]]; do
        path=${path/${BASH_REMATCH[0]}/}
    done
    echo "$path"
}

if test -x /usr/bin/realpath; then
    abspath() {
        if [[ -d "$1" || -d "$(dirname "$1")" ]]; then
            /usr/bin/realpath "$1"
        else
            case "$1" in
                "" | ".") echo "$PWD";;
                /*) normpath "$1";;
                *)  normpath "$PWD/$1";;
            esac
        fi
    }
else
    abspath() {
        if [[ -d "$1" ]]; then
            (cd "$1" && pwd)
        else
            case "$1" in
                "" | ".") echo "$PWD";;
                /*) normpath "$1";;
                *)  normpath "$PWD/$1";;
            esac
        fi
    }
fi

USER_GROUPS=
USER_PASSWORD=
USER_FULLNAME=
USER_IS_ADMIN=
HOST_PATTERN=
USER_PUBLIC_KEY_FILE=
NO_ECHO=yes

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
        -g | --groups)
            USER_GROUPS="${USER_GROUPS}${USER_GROUPS:+,}$2"
            shift 2
            ;;
        --groups=*)
            USER_GROUPS="${USER_GROUPS}${USER_GROUPS:+,}${1#*=}"
            shift
            ;;
        --echo)
            NO_ECHO=
            shift
            ;;
        -f | --full-name)
            USER_FULLNAME="$2"
            shift 2
            ;;
        --full-name=*)
            USER_FULLNAME="${1#*=}"
            shift
            ;;
        -k|--user-public-key-file)
            USER_PUBLIC_KEY_FILE="$2"
            shift 2
            ;;
        --user-public-key-file=*)
            USER_PUBLIC_KEY_FILE="${1#*=}"
            shift
            ;;
        -a | --admin)
            USER_IS_ADMIN=true
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

if [[ -n "$1" ]]; then
    USER_NAME=$1
    shift
else
    fatal "No user name specified"
fi

if [[ -n "$1" ]]; then
    USER_PASSWORD=$1
    shift
fi

USER_GROUPS=${USER_GROUPS// /,}
if [[ -n "$USER_GROUPS" ]]; then
    echo "Add user '$USER_NAME' to $USER_GROUPS groups"
else
    echo "Add user '$USER_NAME'"
fi
if [[ -n "$USER_PASSWORD" ]]; then
    echo "And set user password"
fi

if [[ -n "$USER_PUBLIC_KEY_FILE" ]]; then
    USER_PUBLIC_KEY_FILE=$(abspath "$USER_PUBLIC_KEY_FILE")
fi

jsquote() {
    local arg=$1
    arg=${arg//\"/\\\"}
    echo "\"${arg}\""
}

EXTRA_VARS="{\"user_name\": $(jsquote "$USER_NAME"), \"user_groups\": $(jsquote "$USER_GROUPS")"
if [[ -n "$USER_PASSWORD" ]]; then
    EXTRA_VARS="$EXTRA_VARS, \"user_password\": $(jsquote "$USER_PASSWORD")"
fi
if [[ -z "$USER_FULLNAME" ]]; then
    USER_FULLNAME=$USER_NAME
fi
EXTRA_VARS="$EXTRA_VARS, \"user_fullname\": $(jsquote "$USER_FULLNAME")"
if [[ "$USER_IS_ADMIN" = "true" ]]; then
    EXTRA_VARS="$EXTRA_VARS, \"user_is_admin\": true"
fi
if [[ -n "$USER_PUBLIC_KEY_FILE" ]]; then
    EXTRA_VARS="$EXTRA_VARS, \"user_public_key_file\": $(jsquote "$USER_PUBLIC_KEY_FILE")"
fi
if [[ -n "$HOST_PATTERN" ]]; then
    EXTRA_VARS="$EXTRA_VARS, \"target\": $(jsquote "$HOST_PATTERN")"
fi
EXTRA_VARS="${EXTRA_VARS}"'}'

OPTS=(--extra-vars "$EXTRA_VARS")
if [[ -n "$HOST_PATTERN" ]]; then
    OPTS+=(-l "$HOST_PATTERN")
fi

run-ansible-playbook \
    "${OPTS[@]}" \
    "$ANSIBLE_PLAYBOOKS_DIR/add-user.yml" \
    "$@"
