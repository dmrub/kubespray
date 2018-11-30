#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "$BASH_SOURCE")" && pwd -P) )

source "$THIS_DIR/init-env.sh"

set -e
run-ansible-playbook \
    --extra-vars="dest_dir=$ROOT_DIR" \
    "$ANSIBLE_PLAYBOOKS_DIR/create-ssh-scripts.yml" \
    "$@"
