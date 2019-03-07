#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

set -e

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/disable-firewall.yml" "$@"

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/disable-swap.yml" "$@"

run-ansible all -m setup

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/scale.yml" --become --become-user=root "$@"
