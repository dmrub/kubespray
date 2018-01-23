#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

source "$THIS_DIR/init-env.sh"

echo ansible -i "$ANSIBLE_INVENTORY" \
     --user "$ANSIBLE_REMOTE_USER" \
     "$@"

ansible -i "$ANSIBLE_INVENTORY" \
        --user "$ANSIBLE_REMOTE_USER" \
        --extra-vars @"$CLM_VAULT_FILE" \
        --extra-vars @"$CLM_VARS_FILE" \
        "$@"
