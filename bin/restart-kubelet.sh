#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

ansible all -v -i "$ANSIBLE_INVENTORY" \
        --user "$ANSIBLE_REMOTE_USER" \
        --extra-vars @"$CLM_VAULT_FILE" \
        --extra-vars @"$CLM_VARS_FILE" \
        --become \
        -m shell --args 'systemctl is-active kubelet && systemctl restart kubelet'
