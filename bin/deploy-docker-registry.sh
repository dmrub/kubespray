#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

set -eo pipefail

run-ansible all -m setup || true;

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/deploy-docker-registry.yml" "$@"
