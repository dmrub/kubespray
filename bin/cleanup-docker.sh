#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

$THIS_DIR/run-shell.sh -b 'DP=$(docker ps -q -f status=exited) && [ -n "$DP" ] && docker rm $DP || true; DI=$(docker images -f "dangling=true" -q) && [ -n "$DI" ] && docker rmi $DI || true;'
