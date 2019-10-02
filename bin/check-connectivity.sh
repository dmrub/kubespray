#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

set -eo pipefail

echo >&2 "+ $THIS_DIR/kubectl.sh get svc netchecker-service -o go-template  --template '{{ range .spec.ports}}{{ .nodePort }} {{ end }}'"
OUTPUT=$("$THIS_DIR/kubectl.sh" get svc netchecker-service -o go-template  --template '{{ range .spec.ports}}{{ .nodePort }} {{ end }}')

IFS=" " read -r -a NODE_PORTS <<< "$OUTPUT"

if [[ "${#NODE_PORTS[@]}" -eq 0 ]]; then
    echo >&2 "FATAL: No netchecker-service node ports found !"
    exit 1
fi

"$THIS_DIR/run-ansible.sh" k8s-cluster -m uri -a "url=http://127.0.0.1:${NODE_PORTS[0]}/api/v1/connectivity_check return_content=yes"
