# Operator private notes (non-secret facts to copy-paste)

**This file is safe to commit** — it has **no** real keys or passwords, only empty fields and examples.

**How to use**

1. Copy this file to a **local, gitignored** path you edit whenever facts change:
   ```bash
   cp docs/OPERATOR-PRIVATE-NOTES.example.md docs/OPERATOR-PRIVATE-NOTES.md
   ```
2. Fill in **`docs/OPERATOR-PRIVATE-NOTES.md`** with **your** Droplet IP, **full path to your SSH private key on the machine where you run `ssh`/`scp`** (usually your laptop), and **which repo directory on the server** you use. That file is listed in **`.gitignore`** — it will **not** be committed.
3. Keep **super-secret** values only in **`deploy/secrets.env`** (tokens, DB passwords, `INTERNAL_API_KEY`, Slack IDs/tokens). Never put those here.

See also [DROPLET_REPO_PATH.md](DROPLET_REPO_PATH.md) for **`/opt/parking-acquisition-agents`** vs **`/opt/workspaces/parkinglot`**.

---

## Droplet

| Field | Your value (example shape only) |
|-------|----------------------------------|
| **Public IPv4 or hostname** | `209.x.x.x` or `ubuntu-s-…` |
| **SSH user** | Usually `root` (or `deploy` if you created one) |
| **Repo path on Droplet** (pick one you actually use) | `/opt/parking-acquisition-agents` **or** `/opt/workspaces/parkinglot` |

---

## Path to your **SSH private key** (the “real key path”)

This is a **file on the computer that runs** `ssh` / `scp` (usually your **laptop**), not on the Droplet.

| OS | Example paths (yours will differ) |
|----|-----------------------------------|
| macOS / Linux | `/home/yourname/.ssh/id_ed25519` or `…/id_rsa` |
| Windows (Git Bash) | `/c/Users/YourName/.ssh/id_ed25519` |
| DigitalOcean download | Often `…/Downloads/my-droplet-key.pem` |

**Your actual path (fill in `OPERATOR-PRIVATE-NOTES.md`):**

```
(paste full path to the .pem or private key file here)
```

**Test SSH** (from the machine that has the key):

```bash
ssh -i PASTE_FULL_PATH_TO_PRIVATE_KEY root@PASTE_DROPLET_IP
```

**Copy `.env` from Droplet to laptop** (only when you need the file on your laptop — replace placeholders):

```bash
scp -i PASTE_FULL_PATH_TO_PRIVATE_KEY root@PASTE_DROPLET_IP:/opt/parking-acquisition-agents/deploy/.env ./deploy/.env
```

If the repo on the server is under **`/opt/workspaces/parkinglot`**, use that path instead of **`parking-acquisition-agents`**.

**Same machine only** (you are already SSH’d into the Droplet — no key needed):

```bash
cp /opt/parking-acquisition-agents/deploy/.env /opt/workspaces/parkinglot/deploy/.env
```

---

## GitHub / clone (optional)

| Field | Your value |
|-------|------------|
| Repo remote | `git@github.com:…/parkinglot.git` or HTTPS URL |

---

## Useful commands (repo root on Droplet)

| Task | Command |
|------|---------|
| Apply secrets → Docker | `python3 scripts/render_deploy_env.py && docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d` |
| Health check (env keys) | `python3 scripts/check_ae_setup.py --probe` |
| Install logrotate for `logs/*.log` (pilot scripts) | `cd REPO_ROOT && sudo ./scripts/install-logrotate.sh` — see [OPERATIONS.md](OPERATIONS.md#logs-droplet) |
| Operator console snapshot (agent sees same data as UI) | `python3 scripts/operator_console_snapshot.py --probe-ui` |

---

## For maintainers and AI (committed template)

- This file is the **single committed checklist** of which **non-secret** operator facts we track (Droplet IP, SSH key **file path**, repo directory on the server, optional GitHub remote).
- When a **new** kind of fact needs to be remembered project-wide, **add a row or section here** (placeholders only), then mirror the value in **`docs/OPERATOR-PRIVATE-NOTES.md`** on machines that use this repo.
- **Agents:** before writing SSH/`scp` instructions, read this file and the gitignored `OPERATOR-PRIVATE-NOTES.md` if present; use real values from the latter when available.
