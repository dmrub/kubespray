#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

ansible all -i "$ANSIBLE_INVENTORY" \
        --become \
        -m shell --args 'iptables -t nat -S DOCKER' --become
