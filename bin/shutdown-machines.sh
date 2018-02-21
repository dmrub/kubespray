#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

run-ansible-playbook \
    "$ANSIBLE_PLAYBOOKS_DIR/shutdown-machines.yml" "$@"
