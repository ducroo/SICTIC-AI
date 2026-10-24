# Rebuild the review host

This is the host setup for the review API at https://api.sictic.ch. The pitch deck skill and the Firebase Hosting front end (`https://review.sictic.ch`) are the rest of this branch. A new VM needs the steps below. Certificates, model weights, the Qdrant database, and `.env` stay off git.

## Machine

Use an Ubuntu VM with an NVIDIA GPU and a working driver. The current host is a KVM guest with an L4 (24 GB). The public API needs a public IPv4 address. The DNS A record `api.sictic.ch` must point at that address before Caddy asks for a certificate. The UI hostname `review.sictic.ch` points at Firebase Hosting, not this VM.

Install Podman and Ollama. Ollama's own installer creates `ollama.service`.

## Cloud Agent SSH

Cursor Cloud Agents do not keep a local SSH key across machines. Store the private key as the environment secret `VPS_SSH_PRIVATE_KEY`. `scripts/cloud-agent-start.sh` writes it to `~/.ssh/id_ed25519` on every boot.

Put this public key in `/home/ubuntu/.ssh/authorized_keys` on the VPS:

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIIVTlTu3uFrNSty9ZDPGTi1ERcRWF3a+AZaapGPnaTW cursor-cloud-agent@review-vps
```

Fingerprint: `SHA256:dGpGha1W4F63q8PF+hEWEFaK+k0EBCxKoL5RE1EPmb4`

From a Cloud Agent that has the secret:

```bash
ssh review-vps
# or
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 ubuntu@217.20.195.232
```

## Application

Clone this branch into the ubuntu home directory. Install Miniforge, then run `./install.sh` so the Conda environment from the installer exists. Create `.env` from `.env-template` and keep the document converter and the Ollama model names from that template.

Pull the three models named there.

```bash
ollama pull qwen3:8b
ollama pull qwen3-vl:8b
ollama pull qwen3-embedding:8b
```

On this GPU, do not use the template's Ollama parallelism. The template allows a context of 32768, 8 parallel requests, and 2 loaded models. The L4 runs one model with a context of 8192. Put that in `/etc/systemd/system/ollama.service.d/sictic.conf`.

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_CONTEXT_LENGTH=8192"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_FLASH_ATTENTION=1"
```

Then `sudo systemctl daemon-reload` and `sudo systemctl restart ollama`.

Start Qdrant from the repository. `./launch.sh start` downloads the binary into `qdrant/` and keeps data in `qdrant_data/`. That process is not a systemd service. A reboot does not start it again until someone runs `./launch.sh start`.

## Web page

The page listens on localhost only. Save this as `/etc/systemd/system/spike-web.service`.

```ini
[Unit]
Description=SICTIC spike web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/SICTIC-AI  # pragma: allowlist secret
Environment=PORT=8080
Environment=REPO_PATH=/home/ubuntu/SICTIC-AI  # pragma: allowlist secret
Environment=HOME=/home/ubuntu
ExecStart=/home/ubuntu/miniforge3/envs/sictic-env/bin/python -c "from aiohttp import web; from spike.web import create_app; web.run_app(create_app(), host='127.0.0.1', port=8080)"
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable it with `sudo systemctl enable --now spike-web.service`.

## HTTPS

Caddy is the public entry. It terminates TLS for `api.sictic.ch` and proxies to `127.0.0.1:8080`. Let's Encrypt certificates are stored under `/home/ubuntu/caddy/data` and are requested again on a new machine. Port 443 must be reachable from the internet.

`/home/ubuntu/caddy/Caddyfile`

```
{
	admin off
}
api.sictic.ch {
	reverse_proxy 127.0.0.1:8080
}
```

`/etc/systemd/system/caddy-podman.service`

```ini
[Unit]
Description=Caddy reverse proxy (podman)
After=network-online.target spike-web.service
Wants=spike-web.service

[Service]
Type=simple
ExecStartPre=-/usr/bin/podman rm -f caddy
ExecStart=/usr/bin/podman run --name caddy --network host --pull=missing -v /home/ubuntu/caddy:/etc/caddy:ro -v /home/ubuntu/caddy/data:/data -v /home/ubuntu/caddy/config:/config docker.io/library/caddy:2
ExecStop=/usr/bin/podman stop -t 15 caddy
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Create `/home/ubuntu/caddy/data` and `/home/ubuntu/caddy/config`, then `sudo systemctl enable --now caddy-podman.service`. Caddy redirects port 80 to HTTPS and obtains the certificate by itself once the A record is in place.

The raw IP has no public certificate. Open the API at `https://api.sictic.ch`. The UI is at `https://review.sictic.ch` (Firebase Hosting).

## REST API

Public users use `https://review.sictic.ch` (Firebase Hosting). This host exposes the JSON API:

- `POST /api/review` with multipart field `deck` starts a job.
- `GET /api/review/{job_id}` returns progress and, when finished, `report_html`.

Those two routes require a Firebase App Check token in the `X-Firebase-AppCheck` header and a Firebase Auth ID token in the `Authorization: Bearer …` header when `FIREBASE_PROJECT_ID` is set.

The on-host HTML UI (`/`, `/review`, `/static`, `/review/start`) is **off by default**. Set `SPIKE_SERVE_UI=1` in `.env` and restart `spike-web` only when you need that page for testing on the VPS.

On the VPS `.env`, set:

```
FIREBASE_PROJECT_ID=review-deck-a3c26
FIREBASE_SERVICE_ACCOUNT_JSON=<one-line JSON or leave unset; verification uses the public JWKS>
SPIKE_REQUIRE_AUTH=1
SPIKE_SERVE_UI=
SPIKE_CORS_ORIGINS=https://review.sictic.ch,https://review-deck-a3c26.web.app,https://review-deck-a3c26.firebaseapp.com
```

App Check and Auth verification read the public Firebase JWKS endpoints. The service-account JSON is optional for that path. Keep it as a secret if you use Admin SDK calls later.

## Firebase Hosting

The front end lives under `spike/hosting/public` and deploys from `spike/` with the Firebase project `review-deck-a3c26`. Custom domain: `review.sictic.ch` (CNAME to `review-deck-a3c26.web.app` plus the Hosting ownership TXT).

1. Auth providers are defined in `spike/firebase.json` (`emailPassword` and `googleSignIn`). Deploy them with `firebase deploy --only auth --project review-deck-a3c26`.
2. In Firebase Auth → Settings → Authorized domains, include `review.sictic.ch` (required when `authDomain` in `config.js` is that host).
3. In Firebase Auth → Templates, edit any email template → **customize action URL** →
   `https://review.sictic.ch/__/auth/action`
   (keeps verification / reset links on your domain instead of `*.firebaseapp.com`).
4. In the Firebase console, open App Check for the web app "Pitch deck review".
5. Register the **reCAPTCHA Enterprise** provider (not classic reCAPTCHA v3) and copy the site key into `spike/hosting/public/config.js` as `recaptchaSiteKey`. Allow `review.sictic.ch` on that site key. The Hosting app uses `ReCaptchaEnterpriseProvider`.
6. From `spike/`, deploy Hosting:

```bash
firebase deploy --only hosting --project review-deck-a3c26
```

The Hosting app sends visitors to `/login.html` first (Google or email/password), then calls `https://api.sictic.ch/api/review` with App Check and Auth tokens. `/privacy.html` states the retention rules (account details 60 days; uploaded decks deleted after review).

## Email reports via `gws` (optional, testing)

When `SPIKE_EMAIL_REPORTS=1`, a finished `/api/review` job can email the report
(with PDF attachment) to the signed-in Firebase Auth address using `gws`, but
only when the upload includes `email_results=1` (Hosting checkbox).

PDF files are generated with Chromium print via Playwright (`spike/report_pdf.py`),
matching the Hosting print layout, and are available at
`GET /api/review/{job_id}/pdf`. WeasyPrint remains a fallback. On the VPS:

```bash
conda activate sictic-env
pip install playwright
playwright install-deps chromium
playwright install chromium
# optional fallback:
conda install -y -c conda-forge weasyprint
```

### Install `gws` on the VPS

```bash
mkdir -p "$HOME/bin"
curl -fsSL -o /tmp/gws.tar.gz \
  https://github.com/googleworkspace/cli/releases/download/v0.22.5/google-workspace-cli-x86_64-unknown-linux-gnu.tar.gz
mkdir -p /tmp/gws-extract && tar -xzf /tmp/gws.tar.gz -C /tmp/gws-extract
cp /tmp/gws-extract/gws "$HOME/bin/gws"
chmod +x "$HOME/bin/gws"
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.profile
"$HOME/bin/gws" --version
```

Prefer a newer release tag from https://github.com/googleworkspace/cli/releases when available.

### OAuth (one-time)

Desktop OAuth cannot complete its localhost callback from a laptop against a
process on the VPS. Authenticate where a browser can reach `localhost`, then
export credentials onto the VPS:

1. In GCP project **`ai-sictic`** (current Desktop OAuth client): enable
   **Gmail API**, OAuth consent (External + Testing), add **`ai@sictic.ch`**
   as a **Test user**. Reuse the existing Desktop OAuth client JSON as
   `~/.config/gws/client_secret.json` on the machine where you log in.
2. On your **laptop** (preferred — browser + localhost callback). Sign in as
   **`ai@sictic.ch`** (sender), not a personal test inbox:

```bash
export PATH="$HOME/bin:$PATH"
export GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file
gws auth login -s gmail          # choose ai@sictic.ch
gws auth export --unmasked > ~/gws-credentials.json
chmod 600 ~/gws-credentials.json
```

3. Copy `gws-credentials.json` to the VPS as
   `/home/ubuntu/.config/gws/credentials.export.json` (mode `600`).
   Optionally also set Cloud Agent secret `GWS_CREDENTIALS_JSON` to that file’s
   contents so agents can install it automatically.
4. On the VPS `.env` (keys are already stubbed; set the flag when ready):

```
SPIKE_EMAIL_REPORTS=1
SPIKE_GWS_BIN=/home/ubuntu/bin/gws
GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/home/ubuntu/.config/gws/credentials.export.json
GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file
```

5. Restart the API:

```bash
sudo systemctl restart spike-web.service
```

6. Smoke test (From: `ai@sictic.ch`, To: your inbox, e.g. `urs@gubser.ch`):

```bash
export PATH="$HOME/bin:$PATH"
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/home/ubuntu/.config/gws/credentials.export.json
export GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file
gws gmail +send --to 'urs@gubser.ch' --subject 'gws test' --body 'hello from ai@sictic.ch'
```

Mail is always sent **as `ai@sictic.ch`**. The review API recipient is the
signed-in Firebase Auth address.

### Cursor Cloud Agents

Store `VPS_SSH_PRIVATE_KEY` as today. To use `gws` from a Cloud Agent:

1. Install the Linux binary into `$HOME/bin` (same commands as the VPS).
2. Complete `gws auth login -s gmail` in the agent environment (browser on that
   machine), **or** copy an exported credentials file into the agent and set
   `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE`.
3. Set `GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND=file` so credentials work without
   an OS keychain.
4. Agent insight emails still go through [skills/send_gmail](../skills/send_gmail/SKILL.md);
   the review API uses `spike/email_report.py` instead.

## Auth profile purge (daily)

Firebase Auth has no built-in 60-day purge for email/Google accounts. The VPS runs a systemd timer that calls `python -m spike.purge_auth_users --days 60`. Unit files live in `spike/systemd/`. The service uses `WorkingDirectory=/home/ubuntu/app`, so point that path at the repo checkout (symlink is fine):

```bash
ln -sfn /home/ubuntu/SICTIC-AI /home/ubuntu/app  # pragma: allowlist secret
sudo cp spike/systemd/purge-auth-users.service /etc/systemd/system/
sudo cp spike/systemd/purge-auth-users.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now purge-auth-users.timer
# optional one-shot test:
sudo systemctl start purge-auth-users.service
journalctl -u purge-auth-users.service -n 50 --no-pager
```

Needs `FIREBASE_SERVICE_ACCOUNT_JSON` in the VPS `.env`. The timer fires daily at 03:15 local time (`Persistent=true` catches up after downtime).
