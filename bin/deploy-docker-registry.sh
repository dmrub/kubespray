#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

set -e

run-ansible all -m setup

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/deploy-docker-registry.yml" "$@"
