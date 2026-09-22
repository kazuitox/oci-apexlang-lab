#!/usr/bin/env bash
set -Eeuo pipefail

# Keep Ansible/timeout's exit status even when output is copied into a log.
run_logged() {
  local logfile=$1
  shift
  local results
  set +e
  "$@" 2>&1 | tee -a "$logfile"
  results=("${PIPESTATUS[@]}")
  set -e
  if (( results[0] != 0 )); then return "${results[0]}"; fi
  return "${results[1]}"
}

configure_ansible_environment() {
  # Ansible checks the OS locale, so Python's UTF-8 mode alone is insufficient.
  export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 ANSIBLE_NOCOLOR=1 PYTHONUNBUFFERED=1
  local codeset
  codeset=$(locale charmap) || return $?
  if [[ "$codeset" != "UTF-8" ]]; then
    echo "Ansible requires UTF-8; locale charmap returned: $codeset" >&2
    return 1
  fi
  echo "Ansible locale: $LC_ALL ($codeset)"
}

main() (
  [[ $(id -u) == 0 ]] || { echo 'Run this deployment wrapper with sudo.' >&2; return 1; }
  local deploy_dir
  deploy_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  mkdir -p /var/lib/apexlang
  exec 9>/var/lib/apexlang/ansible.lock
  flock -n 9 || { echo 'Another Ansible deployment is running.' >&2; return 1; }
  local secret_dir=''
  # The subshell keeps these locals alive until EXIT, including failed downloads/Ansible.
  trap 'rm -f -- "$deploy_dir/bootstrap-secrets.json"; if [[ -n "$secret_dir" ]]; then rm -rf -- "$secret_dir"; fi' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  local previous_umask
  previous_umask=$(umask)
  umask 077
  secret_dir=$(mktemp -d /run/apexlang-init.XXXXXX)
  install -m 600 -o root -g root "$deploy_dir/bootstrap-secrets.json" "$secret_dir/secrets.json"
  rm -f -- "$deploy_dir/bootstrap-secrets.json"
  umask "$previous_umask"
  echo '[1/3] Waiting for OS initialization'
  timeout --foreground 45m cloud-init status --wait || return $?
  echo '[2/3] Installing the Ansible controller on this OL8 Arm VM'
  dnf -y install python3.11 python3.11-pip glibc-langpack-en
  configure_ansible_environment
  if [[ ! -x /opt/apexlang/ansible/bin/python ]]; then
    python3.11 -m venv /opt/apexlang/ansible
  fi
  /opt/apexlang/ansible/bin/pip install --disable-pip-version-check 'ansible-core==2.19.8'
  echo '[3/3] Running Ansible tasks; Apply succeeds only when the playbook succeeds'
  touch /var/log/apexlang-ansible.log
  chmod 0640 /var/log/apexlang-ansible.log
  cd "$deploy_dir"
  run_logged /var/log/apexlang-ansible.log timeout --foreground 120m \
    /opt/apexlang/ansible/bin/ansible-playbook -i localhost, -c local \
    -e ansible_python_interpreter=/usr/bin/python3.11 \
    -e @config.json -e "bootstrap_secrets_file=$secret_dir/secrets.json" playbooks/site.yml
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
