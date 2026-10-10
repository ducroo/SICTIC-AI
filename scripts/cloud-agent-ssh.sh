#!/usr/bin/env bash
# Materialize the VPS SSH private key from a Cloud Agent secret.
# The public key is documented in spike/SETUP.md and must be present in
# ~/.ssh/authorized_keys on the VPS. Never commit the private key.
#
# Expected secret:
#   VPS_SSH_PRIVATE_KEY  full OpenSSH private key (ed25519)
# Optional:
#   VPS_SSH_HOST         default ubuntu@217.20.195.232
#
# shellcheck shell=bash

materialize_vps_ssh_key() {
  local key_dir="${HOME}/.ssh"
  local key_path="${key_dir}/id_ed25519"
  local raw="${VPS_SSH_PRIVATE_KEY:-}"

  if [ -z "$raw" ]; then
    return 0
  fi

  mkdir -p "$key_dir"
  chmod 700 "$key_dir"

  # Secrets UIs sometimes store literal \n sequences.
  if printf '%s' "$raw" | grep -q '\\n'; then
    printf '%s\n' "$raw" | sed 's/\\n/\n/g' > "$key_path"
  else
    printf '%s\n' "$raw" > "$key_path"
  fi
  chmod 600 "$key_path"

  if [ ! -f "${key_path}.pub" ] && command -v ssh-keygen >/dev/null 2>&1; then
    ssh-keygen -y -f "$key_path" > "${key_path}.pub"
    chmod 644 "${key_path}.pub"
  fi

  if [ ! -f "${key_dir}/config" ]; then
    cat > "${key_dir}/config" <<EOF
Host review-vps
  HostName 217.20.195.232
  User ubuntu
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
    chmod 600 "${key_dir}/config"
  fi
}
