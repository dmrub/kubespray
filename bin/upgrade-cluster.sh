#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

source "$THIS_DIR/init-env.sh"

set -e

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/disable-firewall.yml" "$@"

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/disable-swap.yml" "$@"

run-ansible all -m setup

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/upgrade-cluster.yml" --become --become-user=root "$@"
