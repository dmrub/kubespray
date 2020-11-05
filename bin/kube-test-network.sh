#!/usr/bin/env bash

set -eo pipefail
export LC_ALL=C
unset CDPATH

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

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

IFS=" " read -r -a NODES <<< "$(run-kubectl get node -o go-template --template '{{range .items}} {{.metadata.name}}{{end}}')"

JOB_NAMES=()
JOB_NS=default

message "Test network on all nodes"

for NODE in "${NODES[@]}"; do
    JOB_NAME=test-network-$NODE
    message "Create job $JOB_NAME for node $NODE"

    if ! RESULT=$(run-kubectl get job \
                    --namespace="$JOB_NS" \
                    -o go-template="{{range.items}}{{if eq .metadata.name \"$JOB_NAME\"}}true{{end}}{{end}}");
    then
        fatal "Could not get jobs in namespace $JOB_NS"
    fi

    if [[ "$RESULT" = "true" ]]; then
        JOB_NAMES+=("$JOB_NAME")
    else
        # Create job first
        if ! run-kubectl apply -f- <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: "$JOB_NAME"
  namespace: "$JOB_NS"
spec:
  template:
    spec:
      containers:
      - name: test
        image: ubuntu
        command:
          - "/bin/sh"
        args:
          - "-c"
          - |
            set -xe;
            apt-get update -y;
            apt-get install -y dnsutils iputils-ping iputils-tracepath;
            ping -c5 8.8.8.8;
            nslookup google.com;
            ping -c5 google.com;
            tracepath -n 8.8.8.8;
      restartPolicy: Never
      nodeName: "$NODE"
  backoffLimit: 4
EOF
        then
            fatal "Failed to create job $JOB_NAME on node $NODE"
        else
            message "Created job $JOB_NAME on node $NODE"
            JOB_NAMES+=("$JOB_NAME")
        fi
    fi
done


for JOB_NAME in "${JOB_NAMES[@]}"; do
    message "Waiting for job $JOB_NAME in namespace $JOB_NS ..."
    JOB_COMPLETE=

    while true; do
        if RESULT=$(run-kubectl get jobs \
                        --namespace="$JOB_NS" \
                        "$JOB_NAME" \
                        -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}');
        then
            if [[ "$RESULT" = "True" ]]; then
                JOB_COMPLETE=false
                break
            fi
        else
            fatal "Could not wait for job $JOB_NAME in namespace $JOB_NS"
        fi
        if RESULT=$(run-kubectl get jobs \
                        --namespace="$JOB_NS" \
                        "$JOB_NAME" \
                        -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}');
        then
            if [[ "$RESULT" = "True" ]]; then
                JOB_COMPLETE=true
                break
            fi
        else
            fatal "Could not wait for job $JOB_NAME in namespace $JOB_NS"
        fi
        sleep 5
    done

    if [[ "$JOB_COMPLETE" != "true" ]]; then
        fatal "Job $JOB_NAME in namespace $JOB_NS failed"
    else
        message "Job $JOB_NAME in namespace $JOB_NS complete, deleting"
        run-kubectl delete --namespace="$JOB_NS" job "$JOB_NAME"
    fi
done

message "Test successfully completed"
