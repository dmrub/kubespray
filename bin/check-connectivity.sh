#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

set -e

NODE_PORTS=( $($THIS_DIR/kubectl.sh get svc netchecker-service -o go-template  --template '{{ range .spec.ports}}{{ .nodePort }} {{ end }}') )

$THIS_DIR/run-ansible.sh all -m uri -a "url=http://localhost:${NODE_PORTS[0]}/api/v1/connectivity_check return_content=yes"
