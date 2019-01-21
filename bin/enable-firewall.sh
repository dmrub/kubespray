#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

ansible all -v -i "$ANSIBLE_INVENTORY" \
        --become \
        -m shell \
        --args 'systemctl enable firewalld; systemctl start firewalld'
