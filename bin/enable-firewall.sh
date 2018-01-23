#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

ansible all -v -i "$ANSIBLE_INVENTORY" \
        --become \
        -m shell \
        --args 'systemctl enable firewalld; systemctl start firewalld'
