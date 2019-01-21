#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

set -e
run-ansible-playbook \
    --extra-vars="dest_dir=$ROOT_DIR" \
    "$ANSIBLE_PLAYBOOKS_DIR/create-ssh-scripts.yml" \
    "$@"
