#!/usr/bin/env bash

THIS_DIR=$( (cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) )

set -eo pipefail

LOCAL_PORT=58079

RUN_SSH=$THIS_DIR/../run-ssh.sh

if [[ ! -e "$RUN_SSH" ]]; then
    "$THIS_DIR"/create-ssh-scripts.sh
fi

error() {
    echo >&2 "Error: $*"
}

fatal() {
    error "$@"
    exit 1
}

usage() {
    echo "Run browser with connection via SOCKS tunnel to the remote host"
    echo
    echo "$0 [options] [--] remote-host"
    echo "options:"
    echo "      -b, --browser BROWSER_PATH"
    echo "                             Use specified browser executable"
    echo "      --help                 Display this help and exit"
    echo "      --                     End of options"
    echo ""
    echo "This tool will try to find a compatible browser. If no browser is detected,"
    echo "the browser specified in the command line will be checked first and then"
    echo "the browser defined in the environment variable BROWSER."
}

while [[ "$1" == "-"* ]]; do
    case "$1" in
        -b|--browser)
            BROWSER="$2"
            shift 2
            ;;
        --browser=*)
            BROWSER="${1#*=}"
            shift
            ;;
        --help)
            usage
            exit
            ;;
        --)
            shift
            break
            ;;
        -*)
            fatal "Unknown option $1"
            ;;
        *)
            break
            ;;
    esac
done

if [[ $# -eq 0 ]]; then
    fatal "Remote host missing"
fi

BROWSER_PID=
TMPDIR=$(mktemp -d /tmp/browser-socks.XXXXXXXXXX)
cleanup() {
    if [[ -n "$BROWSER_PID" ]]; then
        kill "$BROWSER_PID" > /dev/null 2>&1 || true;
    fi
    echo "Delete $TMPDIR"
    rm -rf "$TMPDIR"
}

trap cleanup INT TERM EXIT

BROWSER_EXEC=
TMP_EXEC=
for BROWSER_NAME in "${BROWSER}" chromium-browser firefox google-chrome; do
    TMP_EXEC=$(type -p "$BROWSER_NAME" || true)
    if [[ -x "$TMP_EXEC" ]]; then
        BROWSER_EXEC=$TMP_EXEC
        break
    fi
    echo >&2 "Could not find '$BROWSER_NAME' executable !"
done

if [[ ! -x "$BROWSER_EXEC" ]]; then
    fatal "Could not detect any supported browser executable !"
fi

BROWSER_BN=$(basename "$BROWSER_EXEC")

case "$BROWSER_BN" in
    firefox)
        BROWSER_TYPE=firefox
        ;;
    google-chrome|chromium-browser)
        BROWSER_TYPE=chromium
        ;;
    *)
        fatal "Unsupported browser $BROWSER_BN"
        ;;
esac

case "$BROWSER_TYPE" in
    chromium)
        set -x
        "$BROWSER_EXEC" \
            --user-data-dir="$TMPDIR" \
            --proxy-server="socks5://127.0.0.1:${LOCAL_PORT}" \
            --host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE 127.0.0.1" &
        BROWSER_PID=$!
        set +x
        ;;
    firefox)
        cat > "$TMPDIR/user.js" <<EOF
// Mozilla User Preferences

user_pref("app.normandy.first_run", false);
user_pref("network.predictor.cleaned-up", true);
user_pref("network.proxy.socks", "127.0.0.1");
user_pref("network.proxy.socks_port", ${LOCAL_PORT});
user_pref("network.proxy.socks_remote_dns", true);
user_pref("network.proxy.type", 1);
EOF
        set -x
        "$BROWSER_EXEC" --profile "$TMPDIR" &
        BROWSER_PID=$!
        set +x
        ;;
    *)
        fatal "Unsupported browser type $BROWSER_TYPE, should be one of: chromium, firefox"
        ;;
esac

set -x
"$RUN_SSH" -N -D "$LOCAL_PORT" "$@"
