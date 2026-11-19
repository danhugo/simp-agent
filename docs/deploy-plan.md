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
| 5 | HTTPS, domain, built web | ⏳ Caddy + domain (domain not bought yet) |
| 6 | Google OAuth redirect URIs | ⏳ After the domain: add `https://<domain>/...`, keep Testing mode (up to 100 users) |
| 7 | Keep processes running | ⏳ Docker Compose |
| 8 | Monitoring | ⏳ UptimeRobot (free) |

## Next steps

1. Buy a domain and point it at 43.200.82.250.
2. Code: `docker-compose.yml`, `Caddyfile`, production `settings.toml` (`billing.enabled = true`, `mount_scope = "r2"`, `public_url`).
3. Server: install Docker, clone the repo, put `.env` in place (new R2 token, not the ones pasted in chat), `docker compose up -d`.
4. Google Cloud Console: add the redirect URIs and the test users.
5. Check sign-in, chat, an s3fs mount inside E2B with the temporary credentials, and granting points.
6. Set up UptimeRobot.
