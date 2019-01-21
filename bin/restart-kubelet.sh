#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

run-ansible all -v \
            --become \
            -m shell --args 'systemctl is-active kubelet && systemctl restart kubelet'
