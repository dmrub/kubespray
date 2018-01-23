#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

ansible_playbook "$ANSIBLE_INVENTORY" \
                 --user "$ANSIBLE_REMOTE_USER" \
                 --extra-vars @"$CLM_VAULT_FILE" \
                 --extra-vars @"$CLM_VARS_FILE" \
                 "$ANSIBLE_PLAYBOOKS_DIR/shutdown-machines.yml" "$@"
