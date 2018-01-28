#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

source "$THIS_DIR/init-env.sh"

usage() {
    echo "Run script"
    echo
    echo "$0 [options] [-- [ansible-options]] script-name [args ...]"
    echo "options:"
    echo "  -p, --host-pattern=        Ansible host pattern"
    echo "                             (default: $PATTERN)"
    echo "  -b, --become               run operations with become"
    echo "      --help                 Display this help and exit"
    echo "      --                     End of options"
}

HOST_PATTERN=all
BECOME=

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
        -b|--become)
            BECOME=--become
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

SCRIPT=$1
shift

if [ -z "$SCRIPT" ]; then
    fatal "No script file specified"
fi

if [ ! -e "$SCRIPT" ]; then
    fatal "Not a file: $SCRIPT"
fi

ansible -i "$ANSIBLE_INVENTORY" \
        --user "$ANSIBLE_REMOTE_USER" \
        --extra-vars @"$CLM_VAULT_FILE" \
        --extra-vars @"$CLM_VARS_FILE" \
        "$HOST_PATTERN" $BECOME "${ANSIBLE_OPTS[@]}" \
        -m script --args "'$SCRIPT' $@"
