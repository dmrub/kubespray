#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck disable=SC2016
"$THIS_DIR"/run-shell.sh -b 'for FL in status=exited status=dead; do echo "Remove containers with $FL "; X=$(docker ps -q -f $FL) && [ -n "$X" ] && docker rm $X || true; done; DI=$(docker images -f "dangling=true" -q) && [ -n "$DI" ] && docker rmi $DI || true;'
