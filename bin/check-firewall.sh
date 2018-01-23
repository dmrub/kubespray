#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

ansible -i "$ANSIBLE_INVENTORY" \
        --become \
        all -m shell --args "firewall-cmd --state"
