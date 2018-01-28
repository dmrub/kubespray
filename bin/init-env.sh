ROOT_DIR=$THIS_DIR/..
CLM_CONFIG_FILE=${CLM_CONFIG_FILE:-$ROOT_DIR/clm-config.ini}
CLM_CONFIG_FILE_DIR=$(dirname "$CLM_CONFIG_FILE")

ANSIBLE_DIR=$ROOT_DIR
ANSIBLE_PLAYBOOKS_DIR=$ANSIBLE_DIR
ANSIBLE_INVENTORY_DIR=$ROOT_DIR/inventory
ANSIBLE_INVENTORY=$ANSIBLE_INVENTORY_DIR/inventory.cfg

CLM_CONFIG_DIR=${CLM_CONFIG_DIR:-~/.ansible}
CLM_VAULT_FILE=${CLM_VAULT_FILE:-$ROOT_DIR/vault-config.yml}
CLM_VARS_FILE=${CLM_VARS_FILE:-$ROOT_DIR/vars-config.yml}

export ANSIBLE_PRIVATE_KEY_FILE=${ANSIBLE_PRIVATE_KEY_FILE:-~/.ssh/cluster_id_rsa}
export ANSIBLE_VAULT_PASSWORD_FILE=${ANSIBLE_VAULT_PASSWORD_FILE:-${CLM_CONFIG_DIR}/vault_pass.txt}
export ANSIBLE_CONFIG=$ANSIBLE_DIR/ansible.cfg
export ANSIBLE_FILTER_PLUGINS=$ANSIBLE_DIR/filter_plugins
export ANSIBLE_ROLES_PATH=$ANSIBLE_DIR/roles

error() {
    echo >&2 "Error: $@"
}

fatal() {
    error "$@"
    exit 1
}

abspath() {
    readlink -f "${1}" 2>/dev/null || \
        python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${1}"
}

print-info() {
    echo "Current Configuration:"
    echo "Configuration file:            $(abspath "$CLM_CONFIG_FILE")"
    echo
    echo "Ansible inventory file:        $(abspath "$ANSIBLE_INVENTORY")"
    echo "Config directory:              $(abspath "$CLM_CONFIG_DIR")"
    echo "Ansible vault password file:   $(abspath "$ANSIBLE_VAULT_PASSWORD_FILE")"
    echo "Ansible remote user:           $ANSIBLE_REMOTE_USER"
    echo "Ansible private SSH key file:  $(abspath "$ANSIBLE_PRIVATE_KEY_FILE")"
    echo
}

check-config() {
    if [[ ! -d "$CLM_CONFIG_DIR" ]]; then
        fatal "Configuration directory does not exist, run $(abspath "$THIS_DIR/configure.sh")"
    fi
    if [[ ! -e "$ANSIBLE_VAULT_PASSWORD_FILE" ]]; then
        fatal "Ansible vault password file does not exist, run $(abspath "$THIS_DIR/configure.sh")"
    fi
    if [[ -z "$ANSIBLE_REMOTE_USER" ]]; then
        fatal "Remote user name is not configured, run $THIS_DIR/configure.sh"
    fi
    if [[ ! -e "${ANSIBLE_PRIVATE_KEY_FILE}" || ! -e "${ANSIBLE_PRIVATE_KEY_FILE}.pub" ]]; then
        fatal "SSH keys ${ANSIBLE_PRIVATE_KEY_FILE} or ${ANSIBLE_PRIVATE_KEY_FILE}.pub missing, run $(abspath "$THIS_DIR/configure.sh")"
    fi
}

check-inventory() {
    local inv_dir=$(dirname "$1")
    if [[ ! -e "${inv_dir}/group_vars" ]]; then
        fatal "group_vars directory is missing in ${inv_dir} inventory directory"
    fi
}

ansible_playbook() {
    local inventory=$1
    check-config
    check-inventory "$inventory"
    echo "+ ansible-playbook -i $@"
    ansible-playbook -i "$@"
}

run-ansible() {
    echo "+ ansible -i \"$ANSIBLE_INVENTORY\" \
--user \"$ANSIBLE_REMOTE_USER\" \
--extra-vars @\"$CLM_VAULT_FILE\" \
--extra-vars @\"$CLM_VARS_FILE\" \
$*"

    ansible -i "$ANSIBLE_INVENTORY" \
            --user "$ANSIBLE_REMOTE_USER" \
            --extra-vars @"$CLM_VAULT_FILE" \
            --extra-vars @"$CLM_VARS_FILE" \
            "$@"
}

run-ansible-playbook() {
    check-config
    check-inventory "$ANSIBLE_INVENTORY"
    echo "+ ansible-playbook --inventory \"$ANSIBLE_INVENTORY\" \
--user \"$ANSIBLE_REMOTE_USER\" \
--extra-vars @\"$CLM_VAULT_FILE\" \
--extra-vars @\"$CLM_VARS_FILE\" $*"
    ansible-playbook --inventory "$ANSIBLE_INVENTORY" \
                     --user "$ANSIBLE_REMOTE_USER" \
                     --extra-vars @"$CLM_VAULT_FILE" \
                     --extra-vars @"$CLM_VARS_FILE" \
                     "$@"
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
            declare -g "${prefix}${lhs}"="${rhs}"
        fi
    done <<<"$cfg"
}


eval "$("$THIS_DIR/configure.py" --shell-config)"

#if [[ -e "$CLM_CONFIG_FILE" ]]; then
#    read-config-file "$CLM_CONFIG_FILE" "CFG_"
#    export ANSIBLE_REMOTE_USER=${CFG_ANSIBLE_REMOTE_USER:-$ANSIBLE_REMOTE_USER}
#    export ANSIBLE_PRIVATE_KEY_FILE=${CFG_ANSIBLE_PRIVATE_KEY_FILE:-$ANSIBLE_PRIVATE_KEY_FILE}
#    export ANSIBLE_INVENTORY=${CFG_ANSIBLE_INVENTORY:-$ANSIBLE_INVENTORY}
#    if [[ "$ANSIBLE_INVENTORY" != /* ]]; then
#        ANSIBLE_INVENTORY=$(abspath "${CLM_CONFIG_FILE_DIR}/${ANSIBLE_INVENTORY}")
#    fi
#    if [[ "$ANSIBLE_PRIVATE_KEY_FILE" != /* ]]; then
#        ANSIBLE_PRIVATE_KEY_FILE=$(abspath "${CLM_CONFIG_FILE_DIR}/${ANSIBLE_PRIVATE_KEY_FILE}")
#    fi
#fi
