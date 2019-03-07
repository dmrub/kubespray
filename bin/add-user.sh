#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P))

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

usage() {
    echo "Add user"
    echo
    echo "$0 [options] user-name [password]"
    echo "options:"
    echo "  -p, --host-pattern=         Ansible host pattern"
    echo "  -g, --groups=               Groups separated by comma"
    echo "  -k, --user-public-key-file= User public key file"
    echo "      --help                  Display this help and exit"
    echo "      --                      End of options"
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
HOST_PATTERN=
USER_PUBLIC_KEY_FILE=

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
        -k|--user-public-key-file)
            USER_PUBLIC_KEY_FILE="$2"
            shift 2
            ;;
        --user-public-key-file=*)
            USER_PUBLIC_KEY_FILE="${1#*=}"
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
    USERNAME=$1
    shift
else
    fatal "No username specified"
fi

if [[ -n "$1" ]]; then
    USER_PASSWORD=$1
    shift
else
    echo "No password specified, password will be not set"
fi

USER_GROUPS=${USER_GROUPS// /,}

echo "Add user '$USERNAME' to $USER_GROUPS groups"
if [[ -n "$USER_PASSWORD" ]]; then
    echo "And set user password"
fi

USER_PUBLIC_KEY_FILE=$(abspath "$USER_PUBLIC_KEY_FILE")

jsquote() {
    local arg=$1
    arg=${arg//\"/\\\"}
    echo "\"${arg}\""
}

EXTRA_VARS="{\"user_name\": $(jsquote "$USERNAME"), \"user_groups\": $(jsquote "$USER_GROUPS")"
if [[ -n "$USER_PASSWORD" ]]; then
    EXTRA_VARS="$EXTRA_VARS, \"user_password\": $(jsquote "$USER_PASSWORD")"
fi
if [[ -n "$USER_PUBLIC_KEY_FILE" ]]; then
    EXTRA_VARS="$EXTRA_VARS, \"user_public_key_file\": $(jsquote "$USER_PUBLIC_KEY_FILE")"
fi
EXTRA_VARS="${EXTRA_VARS}"'}'

OPTS=(--extra-vars "$EXTRA_VARS")
if [[ -n "$HOST_PATTERN" ]]; then
    OPTS+=(-l "$HOST_PATTERN")
fi

NO_ECHO=yes
run-ansible-playbook \
    "${OPTS[@]}" \
    "$ANSIBLE_PLAYBOOKS_DIR/add-user.yml" \
    "$@"
