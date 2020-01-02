#!/bin/bash

set -eo pipefail

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

# shellcheck source=init-env.sh
source "$THIS_DIR/init-env.sh"

set -x
"$PY" "$THIS_DIR/configure.py" "$@"
