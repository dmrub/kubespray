#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

source "$THIS_DIR/init-env.sh"

usage() {
    echo "Evaluate ansible template"
    echo
    echo "$0 [options] [-- [ansible-options]] template template ..."
    echo "options:"
    echo "  -p, --host-pattern=        ansible host pattern"
    echo "                             (default: $PATTERN)"
    echo "  -b, --become               run operations with become"
    echo "  -v,-vv,-vvv,-vvvv          run in verbose mode"
    echo "      --verbose"
    echo "      --help                 display this help and exit"
    echo "      --                     end of options"
}

HOST_PATTERN=all
BECOME=
ANSIBLE_OPTS=()

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
        -v|-vv|-vvv|-vvvv|--verbose)
            ANSIBLE_OPTS+=("$1")
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

echo ansible -i "$ANSIBLE_INVENTORY" \
     --user "$ANSIBLE_REMOTE_USER" \
     --extra-vars @"$CLM_VAULT_FILE" \
     --extra-vars @"$CLM_VARS_FILE" \
     "$HOST_PATTERN" $BECOME "${ANSIBLE_OPTS[@]}" -m debug --args=msg="$*"

ansible -i "$ANSIBLE_INVENTORY" \
        --user "$ANSIBLE_REMOTE_USER" \
        --extra-vars @"$CLM_VAULT_FILE" \
        --extra-vars @"$CLM_VARS_FILE" \
        "$HOST_PATTERN" $BECOME "${ANSIBLE_OPTS[@]}" -m debug --args=msg="$*"
