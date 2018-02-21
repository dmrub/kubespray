#!/bin/bash

THIS_DIR=$(dirname "$( readlink -f "${BASH_SOURCE}" 2>/dev/null || \
  python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE}" )")

source "$THIS_DIR/init-env.sh"

set -e

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/delete-certs.yml" "$@"

# was k8s-secrets,client
run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/cluster.yml" \
                     --tags k8s-secrets,client \
                     --skip-tags=download \
                     --become --become-user=root "$@"
#                      --tags facts,k8s-secrets,kube-apiserver,etcd,client \

#run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/extra_playbooks/upgrade-only-k8s.yml" \
#                     --skip-tags=download \
#                     --become --become-user=root "$@"

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/restart-cluster.yml" "$@"

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/rotate-tokens.yml" "$@"

run-ansible-playbook "$ANSIBLE_PLAYBOOKS_DIR/restart-cluster.yml" "$@"
