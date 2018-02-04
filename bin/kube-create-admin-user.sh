#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "$BASH_SOURCE")" && pwd -P) )

set -eo pipefail

message() {
    echo >&2 "$*"
}

error() {
    echo >&2 "* Error: $*"
}

fatal() {
    error "$@"
    exit 1
}

run-kubectl() {
    "$THIS_DIR/kubectl.sh" "$@"
}

if ! run-kubectl get clusterrole cluster-admin > /dev/null; then
    fatal "No ClusterRole cluster-admin"
fi

USER_NAME=${1:-admin-user}

message "Create user \"$USER_NAME\""

run-kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${USER_NAME}
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1beta1
kind: ClusterRoleBinding
metadata:
  name: ${USER_NAME}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: ${USER_NAME}
  namespace: kube-system
---
EOF

for i in $(run-kubectl -n kube-system get secret \
                       -o go-template='{{range.items}}{{ .metadata.name }} {{end}}');
do
    if [[ "$i" == ${USER_NAME}-* ]]; then
        run-kubectl -n kube-system describe secret "$i"
        break
    fi
done
