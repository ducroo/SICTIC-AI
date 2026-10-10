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

_normalize_openssh_private_key() {
  # Secrets UIs often collapse PEM newlines into one line. Rebuild the
  # OpenSSH private-key shape: header, 70-column body, footer.
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
import textwrap

raw = Path(sys.argv[1]).read_text()
raw = raw.replace("\\n", "\n").strip()
begin = "-----BEGIN OPENSSH PRIVATE KEY-----"
end = "-----END OPENSSH PRIVATE KEY-----"
if begin not in raw or end not in raw:
    raise SystemExit("VPS_SSH_PRIVATE_KEY is not an OpenSSH private key")
body = raw.split(begin, 1)[1].split(end, 1)[0]
body = "".join(body.split())
wrapped = "\n".join(textwrap.wrap(body, 70))
Path(sys.argv[1]).write_text(f"{begin}\n{wrapped}\n{end}\n")
PY
}

materialize_vps_ssh_key() {
  local key_dir="${HOME}/.ssh"
  local key_path="${key_dir}/id_ed25519"
  local raw="${VPS_SSH_PRIVATE_KEY:-}"

  if [ -z "$raw" ]; then
    return 0
  fi

  mkdir -p "$key_dir"
  chmod 700 "$key_dir"

  printf '%s\n' "$raw" > "$key_path"
  _normalize_openssh_private_key "$key_path"
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
