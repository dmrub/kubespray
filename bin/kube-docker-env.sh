#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "$BASH_SOURCE")" && pwd -P) )

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

_get_children_pids() {
    local pid=$1
    local all_pids=$2
    local children=
    for child in $(awk "{ if ( \$2 == $pid ) { print \$1 } }" <<<"$all_pids");
    do
        children="$(_get_children_pids $child "$all_pids") $child $children"
    done
    echo "$children"
}

get_children_pids() {
    local pid=$1
    local all_pids=$(ps -o pid,ppid -ax)
    _get_children_pids "$pid" "$all_pids"
}


POD_NAME=docker-gateway

while true; do
    PHASE=$(run-kubectl get pod "$POD_NAME" -o template --template '{{ .status.phase }}' 2>/dev/null)
    if [[ $? -ne 0 || \
              "$PHASE" = "Terminating" || \
              "$PHASE" = "Failed" || \
              "$PHASE" = "Succeeded" ]];
    then
        if [[ "$PHASE" = "Failed" || "$PHASE" = "Succeeded" ]]; then
            run-kubectl delete pod "$POD_NAME" >&2
        fi
        message "* Start Pod $POD_NAME"

        cat <<EOF | run-kubectl create -f - >&2
apiVersion: v1
kind: Pod
metadata:
  name: $POD_NAME
spec:
  containers:
  - name: socat
    image: alpine/socat
    args: [ "TCP4-LISTEN:2375,fork,reuseaddr",  "UNIX-CONNECT:/var/run/docker.sock"]
    volumeMounts:
    - mountPath: /var/run/docker.sock
      name: docker-sock
    ports:
    - name: docker
      containerPort: 2375
  volumes:
  - name: docker-sock
    hostPath:
      path: /var/run/docker.sock
EOF

        message "Waiting until Pod is started ..."
        continue
    fi
    if [[ -n "$VERBOSE" ]]; then
        message "* Pod $POD_NAME in phase: $PHASE"
    fi
    if [[ "$PHASE" = "Running" ]]; then
        break
    fi
    sleep 1
done

LOCAL_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
run-kubectl port-forward "$POD_NAME" $LOCAL_PORT:2375 >&2 &
pid=$!

cat <<EOF
export DOCKER_HOST=tcp://127.0.0.1:$LOCAL_PORT;
kube-stop-docker() {
  unset DOCKER_HOST;
  unset -f kube-stop-docker;
  kill $(get_children_pids $pid) $pid;
};
# Run this command to configure your shell:
# eval \$($0)
# Stop port forwarding by running:
# kube-stop-docker
EOF
