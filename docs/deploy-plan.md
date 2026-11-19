# Deploy plan (updated 2026-11-19)

## Decisions

- **Server:** AWS Lightsail `simp-agent`, 2 GB, Ubuntu 24.04, ap-northeast-2 (Seoul), static IP 43.200.82.250, SSH alias `simp-agent`. About $12/month with 3 TB of transfer included.
- **Database:** SQLite stays (one server). Lightsail runs daily automatic snapshots. Continuous backup (Litestream) comes later.
- **User files:** Cloudflare R2 (free egress). Each sandbox gets R2 temporary credentials scoped to `users/<id>/` (`mount_scope = "r2"`, PR #6). Tested live: the creds can read and write their own prefix and are denied everywhere else. R2 has no versioning, so workspace restore is off.
- **Secrets:** a `.env` on the server with `chmod 600`. No AWS S3, IAM or SSM is needed.
- **HTTPS + web:** Caddy serves `/api` from the Python server and the built web (`apps/web/dist`) for everything else, with automatic HTTPS.
- **Processes:** Docker Compose (server, google_mcp, Caddy) with `restart: always`.
- **Billing:** points (1 USD = 1000 points), covering LLM calls and E2B (paused time charged at 10%). New users start at 0 points and the admin grants them with `simp-server credit add`. Billing is off for local installs. Shipped in PR #5.

## The 8 issues

| # | Issue | Status |
|---|---|---|
| 1 | Open sign-up spends our money | ✅ Points: new users have 0 (PR #5) |
| 2 | Store key handed to every sandbox | ✅ R2 temporary credentials per user (PR #6) |
| 3 | Secrets | ✅ Decided: `.env` on the server, `chmod 600` |
| 4 | Backups | ⏸ Daily Lightsail snapshots for now; Litestream later |
| 5 | HTTPS, domain, built web | ✅ `simpagent.app` + `preview.simpagent.app` (Cloudflare proxy on, SSL Full strict); Caddy + compose written |
| 6 | Google OAuth redirect URIs | ⏳ After the domain: add `https://<domain>/...`, keep Testing mode (up to 100 users) |
| 7 | Keep processes running | ✅ Docker Compose (server, caddy; google_mcp later) |
| 8 | Monitoring | ⏳ UptimeRobot (free) |

## Next steps

1. ✅ Domain `simpagent.app` (Cloudflare), A records `@` and `preview` -> 43.200.82.250. For the first certificate: proxy off (grey) and "Always Use HTTPS" off until Caddy has it, then proxy on.
2. Code: `docker-compose.yml`, `Caddyfile`, production `settings.toml` (`billing.enabled = true`, `mount_scope = "r2"`, `public_url`).
3. Server: add 2 GB swap first (building the images on 2 GB RAM can run out of memory: `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab`), install Docker, clone the repo, put `.env` in place (new R2 token, not the ones pasted in chat), `docker compose up -d`.
4. Google Cloud Console: add the redirect URIs and the test users.
5. Check sign-in, chat, an s3fs mount inside E2B with the temporary credentials, and granting points.
6. Set up UptimeRobot.

## CI/CD (GitHub Actions)

`.github/workflows/deploy.yml` deploys a release tag: `git tag v0.1.0 && git push origin v0.1.0`. Pushing to master
(the dev branch) never deploys. Roll back = re-run an older tag from the Actions tab (Run workflow, pick the tag).
It SSHes to the box, rewrites `/srv/simp/.env` from repo secrets, checks out the tag, and runs `docker compose up -d --build server caddy`,
then checks `https://simpagent.app/` answers. `/srv/simp/settings.toml` is rewritten too, from the `SETTINGS_TOML`
repo secret (the whole file; this repo is public, so models, bucket and `allowed_emails` stay out of it).
To change settings: edit the secret, then re-run the tag. Keep your own copy: a secret cannot be read back.

One-time setup:
1. Lightsail firewall: SSH (22) open to any IP (GitHub runners have no fixed IP). Login is key-only.
2. Repo Settings → Secrets and variables → Actions → New repository secret, one per name:
   `SSH_KEY` (the whole .pem file), `SSH_HOST` (43.200.82.250), `OPENROUTER_API_KEY`, `SIMP_SECRET_KEY`, `E2B_API_KEY`,
   `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `R2_API_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
   Make `SIMP_SECRET_KEY` once (on the box: `docker run --rm python:3.13-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"`)
   and never change it: it encrypts users' Google tokens.
