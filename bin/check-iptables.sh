#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

run-ansible all \
        --become \
        -m shell --args 'iptables -t nat -S DOCKER' --become
