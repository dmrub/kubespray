#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

$THIS_DIR/run-shell.sh -b 'printf "*mangle\nCOMMIT\n*nat\nCOMMIT\n*filter\nCOMMIT\n*raw\nCOMMIT\n" | iptables-restore'
