#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "$BASH_SOURCE")" && pwd -P) )

"$THIS_DIR/../artifacts/kubectl" \
    --kubeconfig="$THIS_DIR/../artifacts/admin.conf" \
    "$@"
