#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

ARTIFACTS_DIR=$(dirname "$ANSIBLE_INVENTORY")/artifacts

exec "$ARTIFACTS_DIR/kubectl" \
    --kubeconfig="$ARTIFACTS_DIR/admin.conf" \
    "$@"
