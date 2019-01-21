#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

ansible -i "$ANSIBLE_INVENTORY" \
        --become \
        all -m shell --args "firewall-cmd --state"
