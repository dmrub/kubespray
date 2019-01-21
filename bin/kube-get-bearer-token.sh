#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

run-kubectl() {
    "$THIS_DIR/kubectl.sh" "$@"
}

KUBE_USER=admin-user
SECRETS=$(run-kubectl-ctx -n kube-system get secret -o template -o go-template='{{ range.items }}{{ .metadata.name }}{{"\n"}}{{end}}')

if SECRET=$(grep "$KUBE_USER" <<<"$SECRETS"); then
    run-kubectl-ctx -n kube-system describe secret "$SECRET"
else
    exit 1
fi
