#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

ARTIFACTS_DIR=
TESTED=()

for inventory in "${CFG_ANSIBLE_INVENTORIES[@]}"; do
    for inventory_dir in "$inventory" "$(dirname "$inventory")"; do
        if [[ -d "${inventory_dir}" ]]; then
            if [[ -x "${inventory_dir}/artifacts/kubectl" && -e "${inventory_dir}/artifacts/admin.conf"  ]]; then
                ARTIFACTS_DIR="${inventory_dir}/artifacts"
            else
                TESTED+=( "${inventory_dir}/artifacts" )
            fi
        fi
    done
done

if [[ -z "$ARTIFACTS_DIR" ]]; then
    error "Could not find kubectl executable and/or admin.conf files in artifacts directory."
    echo >&2 "Tested directories:"
    for t in "${TESTED[@]}"; do
        echo >&2 "* $t"
    done
    exit 1
fi

exec "$ARTIFACTS_DIR/kubectl" \
    --kubeconfig="$ARTIFACTS_DIR/admin.conf" \
    "$@"
