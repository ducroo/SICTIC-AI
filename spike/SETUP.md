# Rebuild the review host

This is the host setup for https://review.sictic.ch. The pitch deck skill and the web page are the rest of this branch. A new VM needs the steps below. Certificates, model weights, the Qdrant database, and `.env` stay off git.

## Machine

Use an Ubuntu VM with an NVIDIA GPU and a working driver. The current host is a KVM guest with an L4 (24 GB). The public site needs a public IPv4 address. The DNS A record `review.sictic.ch` must point at that address before Caddy asks for a certificate.

Install Podman and Ollama. Ollama's own installer creates `ollama.service`.

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

Caddy is the public entry. It terminates TLS for `review.sictic.ch` and proxies to `127.0.0.1:8080`. Let's Encrypt certificates are stored under `/home/ubuntu/caddy/data` and are requested again on a new machine. Port 443 must be reachable from the internet.

`/home/ubuntu/caddy/Caddyfile`

```
{
	admin off
}
review.sictic.ch {
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

The raw IP has no public certificate. Open the site at `https://review.sictic.ch`.

## REST API

The HTML page at `/` stays as it is. The same review is also available as JSON:

- `POST /api/review` with multipart field `deck` starts a job.
- `GET /api/review/{job_id}` returns progress and, when finished, `report_html`.

Those two routes require a Firebase App Check token in the `X-Firebase-AppCheck` header when `FIREBASE_PROJECT_ID` is set. The older `/review/start` and `/review/status/{job_id}` routes stay open for the Caddy-hosted page.

On the VPS `.env`, set:

```
FIREBASE_PROJECT_ID=review-deck-a3c26
FIREBASE_SERVICE_ACCOUNT_JSON=<one-line JSON or leave unset; verification uses the public JWKS>
SPIKE_CORS_ORIGINS=https://review-deck-a3c26.web.app,https://review-deck-a3c26.firebaseapp.com
```

App Check verification reads the Firebase JWKS. The service-account JSON is optional for that path. Keep it as a secret if you use Admin SDK calls later.

## Firebase Hosting

The front end lives under `spike/hosting/public` and deploys from `spike/` with the Firebase project `review-deck-a3c26`.

1. In the Firebase console, open App Check for the web app "Pitch deck review".
2. Register the reCAPTCHA v3 provider and copy the site key into `spike/hosting/public/config.js` as `recaptchaSiteKey`.
3. From `spike/`, deploy Hosting:

```bash
firebase deploy --only hosting --project review-deck-a3c26
```

The Hosting app calls `https://review.sictic.ch/api/review` with an App Check token.
