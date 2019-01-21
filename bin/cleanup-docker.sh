#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck disable=SC2016
"$THIS_DIR/run-shell.sh" -b 'DP=$(docker ps -q -f status=exited) && [ -n "$DP" ] && docker rm $DP || true; DI=$(docker images -f "dangling=true" -q) && [ -n "$DI" ] && docker rmi $DI || true;'
