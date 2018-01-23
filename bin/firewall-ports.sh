#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

ansible_playbook "$ANSIBLE_INVENTORY" \
                 "$ANSIBLE_PLAYBOOKS_DIR/firewall-ports.yml" \
                 "$@"
