# shellcheck shell=bash
ROOT_DIR=$THIS_DIR/..
CFG_CONFIG_FILE=${CFG_CONFIG_FILE:-$ROOT_DIR/config.yml}
CFG_CONFIG_FILE_DIR=$(dirname "$CFG_CONFIG_FILE")

ANSIBLE_DIR=$ROOT_DIR
ANSIBLE_PLAYBOOKS_DIR=$ANSIBLE_DIR
ANSIBLE_INVENTORY_DIR=$ROOT_DIR/inventory
CFG_ANSIBLE_INVENTORIES=("$ANSIBLE_INVENTORY_DIR/inventory.cfg")

CFG_CONFIG_DIR=${CFG_CONFIG_DIR:-~/.ansible}
CFG_VAULT_FILE=${CFG_VAULT_FILE:-""}
CFG_VARS_FILE=${CFG_VARS_FILE:-""}

export ANSIBLE_PRIVATE_KEY_FILE=${ANSIBLE_PRIVATE_KEY_FILE:-~/.ssh/cluster_id_rsa}
export ANSIBLE_CONFIG=$ANSIBLE_DIR/ansible.cfg
export ANSIBLE_FILTER_PLUGINS=$ANSIBLE_DIR/filter_plugins
export ANSIBLE_ROLES_PATH=$ANSIBLE_DIR/roles

error() {
    echo >&2 "Error: $*"
}

fatal() {
    error "$@"
    exit 1
}

abspath() {
    readlink -f "${1}" 2>/dev/null || \
        python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${1}"
}

join_by() {
  local IFS="$1"
  shift
  echo "$*"
}

print-info() {
    echo "Current Configuration:"
    echo "Configuration file:            $(abspath "$CFG_CONFIG_FILE")"
    echo

    local inventories inventory vault_password_files vault_password_file
    inventories=()
    for inventory in "${CFG_ANSIBLE_INVENTORIES[@]}"; do
      inventories+=( "$(abspath "$inventory")" )
    done
    vault_password_files=()
    for vault_password_file in "${CFG_ANSIBLE_VAULT_PASSWORD_FILES[@]}"; do
        vault_password_files+=( "$(abspath "$vault_password_file")" )
    done

    echo "Ansible inventory file(s):        $(join_by ", " "${inventories[@]}")"
    echo "Config directory:                 $(abspath "$CFG_CONFIG_DIR")"
    echo "Ansible vault password file(s):   $(join_by ", " "${vault_password_files[@]}")"
    echo "Ansible remote user:              $ANSIBLE_REMOTE_USER"
    echo "Ansible private SSH key file:     $(abspath "$ANSIBLE_PRIVATE_KEY_FILE")"
    echo
}

check-config() {
    if [[ ! -d "$CFG_CONFIG_DIR" ]]; then
        fatal "Configuration directory does not exist, run $(abspath "$THIS_DIR/configure.sh")"
    fi
    #if [[ ! -e "$ANSIBLE_VAULT_PASSWORD_FILE" ]]; then
    #    fatal "Ansible vault password file does not exist, run $(abspath "$THIS_DIR/configure.sh")"
    #fi
    #if [[ -z "$ANSIBLE_REMOTE_USER" ]]; then
    #    fatal "Remote user name is not configured, run $THIS_DIR/configure.sh"
    #fi
    if [[ -n "${ANSIBLE_PRIVATE_KEY_FILE}" ]]; then
        if [[ ! -e "${ANSIBLE_PRIVATE_KEY_FILE}" || ! -e "${ANSIBLE_PRIVATE_KEY_FILE}.pub" ]]; then
            fatal "SSH keys ${ANSIBLE_PRIVATE_KEY_FILE} or ${ANSIBLE_PRIVATE_KEY_FILE}.pub missing, run $(abspath "$THIS_DIR/configure.sh")"
        fi
    fi
}

check-inventory() {
    local inv_dir
    inv_dir=$(dirname "$1")
    #if [[ ! -e "${inv_dir}/group_vars" ]]; then
    #    fatal "group_vars directory is missing in ${inv_dir} inventory directory"
    #fi
}

ansible_playbook() {
    local inventory=$1
    check-config
    check-inventory "$inventory"
    if [[ -z "$NO_ECHO" ]]; then
        echo >&2 "+ ansible-playbook -i $*"
    fi
    ansible-playbook -i "$@"
}

add-inventories-to-opts() {
    # opts array is defined outside
    local inventory
    for inventory in "${CFG_ANSIBLE_INVENTORIES[@]}"; do
      opts+=( -i "$inventory" )
    done
}

add-vault-config-to-opts() {
    local vault_password_file
    for vault_password_file in "${CFG_ANSIBLE_VAULT_PASSWORD_FILES[@]}"; do
        opts+=( "--vault-password-file=$vault_password_file" )
    done
}

add-remote-user-to-opts() {
    # opts array is defined outside
    if [[ -n "$ANSIBLE_REMOTE_USER" ]]; then
        opts+=(--user "$ANSIBLE_REMOTE_USER")
    fi
}

add-extra-vars-to-opts() {
    # opts array is defined outside
    if [[ -e "$CFG_VAULT_FILE" ]]; then
        opts+=(--extra-vars @"$CFG_VAULT_FILE")
    fi
    if [[ -e "$CFG_VARS_FILE" ]]; then
        opts+=(--extra-vars @"$CFG_VARS_FILE")
    fi
}

run-ansible-cmd() {
    # opts array is defined outside
    local cmd
    cmd=$1
    shift

    if [[ -z "$NO_ECHO" ]]; then
        echo >&2 "+ ${cmd} \
${opts[*]} \
$*"
    fi
    "${cmd}" \
        "${opts[@]}" \
        "$@"
}

run-ansible() {
    local opts
    opts=()
    add-inventories-to-opts
    add-vault-config-to-opts
    add-remote-user-to-opts
    add-extra-vars-to-opts

    run-ansible-cmd ansible "$@"
}

run-ansible-inventory() {
    local opts
    opts=()
    add-inventories-to-opts
    add-vault-config-to-opts
    # remote user and extra vars are not supported by ansible-inventory

    run-ansible-cmd ansible-inventory "$@"
}

run-ansible-vault() {
    local opts
    opts=()
    # inventories, remote users and extra vars are not supported by ansible-vault
    add-vault-config-to-opts

    run-ansible-cmd ansible-vault "$@"
}

run-ansible-playbook() {
    check-config

    local opts
    opts=()
    add-inventories-to-opts
    add-vault-config-to-opts
    add-remote-user-to-opts
    add-extra-vars-to-opts

    run-ansible-cmd ansible-playbook "$@"
}

run-ansible-galaxy() {
    local opts
    opts=()

    run-ansible-cmd ansible-galaxy "$@"
}

# $1 - filename
# $2 - variable prefix, CFG_ is used by default
read-config-file() {
    local configfile=$1
    local prefix=$2
    if [[ ! -f "$configfile" ]]; then echo >&2 "[read-config-file] '$configfile' is not a file"; return 1; fi
    if [[ -z "$prefix" ]]; then prefix=CFG_; fi

    local lhs rhs cfg exitcode

    cfg=$(tr -d '\r' < "$configfile")
    exitcode=$?
    if [ "$exitcode" != "0" ]; then return $exitcode; fi

    while IFS='=' read -rs lhs rhs;
    do
        if [[ "$lhs" =~ ^[A-Za-z_][A-Za-z_0-9]*$ && -n "$lhs" ]]; then
            rhs="${rhs%%\#*}"               # Del in line right comments
            rhs="${rhs%"${rhs##*[^ ]}"}"    # Del trailing spaces
            rhs="${rhs%\"*}"                # Del opening string quotes
            rhs="${rhs#\"*}"                # Del closing string quotes
            declare -g "${prefix}${lhs}=${rhs}"
        fi
    done <<<"$cfg"
}

CFG_SHELL_CONFIG=$("$THIS_DIR/configure.py" --shell-config)

eval "$CFG_SHELL_CONFIG"

