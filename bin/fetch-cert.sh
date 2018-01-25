#!/bin/bash

# Based on https://serverfault.com/questions/661978/displaying-a-remote-ssl-certificate-details-using-cli-tools

function fetch-cert() {
    local host=$1
    local port=${2:-443}
    echo | openssl s_client -showcerts -servername "$host" -connect "$host:$port" 2>/dev/null | openssl x509 -inform pem -noout -text
}

if [[ $# -lt 1 ]]; then
    cat >&2 <<EOF
Load certificate of the https web service

Usage: $0 host [port]

       port is 443 by default
EOF
    exit 0
fi

if ! type openssl &> /dev/null; then
    echo >&2 "Fatal error: no openssl tool found"
    exit 1
fi

fetch-cert "$@"
