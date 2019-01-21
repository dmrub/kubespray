#!/bin/bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

"$THIS_DIR/run-shell.sh" -b 'printf "*mangle\nCOMMIT\n*nat\nCOMMIT\n*filter\nCOMMIT\n*raw\nCOMMIT\n" | iptables-restore'
