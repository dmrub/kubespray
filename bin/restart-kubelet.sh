#!/bin/bash

THIS_DIR=$(dirname "$(readlink -f "$BASH_SOURCE")")

source "$THIS_DIR/init-env.sh"

run-ansible all -v \
            --become \
            -m shell --args 'systemctl is-active kubelet && systemctl restart kubelet'
