#!/usr/bin/env bash

set -eo pipefail
export LC_ALL=C
unset CDPATH

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P))

error() {
    echo >&2 "Error: $*"
}

fatal() {
    error "$@"
    exit 1
}

message() {
    echo >&2 "* $*"
}

run-kubectl() {
    "$THIS_DIR/kubectl.sh" "$@"
}

PODS="$(run-kubectl get pods -A -o template -o go-template='{{ range.items }}{{.metadata.name}} {{.metadata.namespace}}{{"\n"}}{{end}}')"

while read -r POD_NAME POD_NS; do
    echo "Pod $POD_NAME in $POD_NS namespace"
    SECRET_NAMES=$(run-kubectl get pod --namespace="$POD_NS" "$POD_NAME" --output="jsonpath={.spec.volumes[*].secret.secretName}")
    while read -r -a SECRET_NAMES_ARRAY; do
        for SECRET_NAME in "${SECRET_NAMES_ARRAY[@]}"; do
            if SECRET_TYPE=$(bin/kubectl.sh get secret -n "$POD_NS" "$SECRET_NAME" --output="jsonpath={.type}"); then
                if [[ "$SECRET_TYPE" = "kubernetes.io/service-account-token" ]]; then
                    echo "Delete Secret $SECRET_NAME in the namespace $POD_NS"
                    run-kubectl delete secret -n "$POD_NS" "$SECRET_NAME" || true;
                fi
            fi
        done
    done <<<"$SECRET_NAMES"

    echo "Delete pod $POD_NAME in the namespace $POD_NS"
    run-kubectl delete pod --wait=false -n "$POD_NS" "$POD_NAME"
done <<<"$PODS"
