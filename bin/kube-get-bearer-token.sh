#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "$BASH_SOURCE")" && pwd -P) )

run-kubectl() {
    "$THIS_DIR/kubectl.sh" "$@"
}

run-kubectl -n kube-system describe secret $(run-kubectl -n kube-system get secret | grep admin-user | awk '{print $1}')
