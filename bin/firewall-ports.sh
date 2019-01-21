#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

ansible_playbook "$ANSIBLE_INVENTORY" \
                 "$ANSIBLE_PLAYBOOKS_DIR/firewall-ports.yml" \
                 "$@"
