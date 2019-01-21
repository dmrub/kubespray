#!/bin/bash

set -eo pipefail
export LC_ALL=C
unset CDPATH

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

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

kube-current-context() {
    run-kubectl config view -o=jsonpath='{.current-context}'
}

_get_children_pids() {
    local pid=$1
    local all_pids=$2
    local children=

    while IFS= read -r child; do
        children="$(_get_children_pids "$child" "$all_pids") $child $children"
    done < <(awk "{ if ( \$2 == $pid ) { print \$1 } }" <<<"$all_pids")

    #for child in $(awk "{ if ( \$2 == $pid ) { print \$1 } }" <<<"$all_pids");
    #do
    #    children="$(_get_children_pids $child "$all_pids") $child $children"
    #done
    echo "$children"
}

get_children_pids() {
    local pid=$1 all_pids
    all_pids=$(ps -o pid,ppid -ax)
    _get_children_pids "$pid" "$all_pids"
}

if [[ "$1" = "--port-forward" ]]; then
    shift

    if [[ $# -lt 3 ]]; then
        echo >&2 "Fatal: --port-forward option require 3 arguments: CFG_DIR POD_NAME LOCAL_PORT"
        exit 1
    fi

    CFG_DIR=$1
    POD_NAME=$2
    LOCAL_PORT=$3
    KUBECTL_PIDS=

    cleanup() {
        if [[ -n "$KUBECTL_PIDS" ]]; then
            echo "Stopping docker port forwarding (pids: $KUBECTL_PIDS)  ..."
            kill $KUBECTL_PIDS 2>/dev/null
            KUBECTL_PIDS=
        fi
        rm -rf "$CFG_DIR"
    }

    trap cleanup INT TERM EXIT
    run-kubectl port-forward "$POD_NAME" "$LOCAL_PORT:2375" &
    WAIT_PID=$!
    KUBECTL_PIDS="$(get_children_pids $WAIT_PID) $WAIT_PID"
    wait $WAIT_PID
    exit $?
fi


POD_NAME=docker-gateway

while true; do
    if ! PHASE=$(run-kubectl get pod "$POD_NAME" -o template --template '{{ .status.phase }}' 2>/dev/null) || \
         [[ \
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

LOCAL_PORT=""
pid=""
CFG_DIR=~/".kube-docker-env-$(kube-current-context)"
if [[ -d "$CFG_DIR" && -e "$CFG_DIR/docker-port" && -e "$CFG_DIR/pid" ]]; then
    LOCAL_PORT=$(<"$CFG_DIR/docker-port")
    pid=$(<"$CFG_DIR/pid")
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$CFG_DIR/pid" "$CFG_DIR/docker-port"
        pid=""
        LOCAL_PORT=""
    fi
fi

if [[ -z "$LOCAL_PORT" || -z "$pid" ]]; then
    mkdir -p "$CFG_DIR"
LOCAL_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
    # run-kubectl port-forward "$POD_NAME" $LOCAL_PORT:2375 >&2 &
    "$0" --port-forward "$CFG_DIR" "$POD_NAME" "$LOCAL_PORT" >&2 &
pid=$!
    echo "$LOCAL_PORT" > "$CFG_DIR/docker-port"
    echo "$pid" > "$CFG_DIR/pid"
fi

cat <<EOF
export DOCKER_HOST=tcp://127.0.0.1:$LOCAL_PORT;
unset DOCKER_TLS_VERIFY
unset DOCKER_CERT_PATH
unset DOCKER_API_VERSION
kube-stop-docker() {
  unset DOCKER_HOST;
  unset -f kube-stop-docker;
  kill $(get_children_pids $pid) $pid;
};

# Run this command to configure your shell:
# eval "\$($0)"
# Stop port forwarding by running:
# kube-stop-docker
EOF
