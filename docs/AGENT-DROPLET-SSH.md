# SSH for agents and operators (Droplet)

Use this when **Cursor**, **Makefile** targets, or **scripts** need **non-interactive** SSH (`BatchMode=yes`) to the parking stack host.

## Canonical host and paths

See [PROJECT-FACTS.md](PROJECT-FACTS.md) for **public IPv4** and **Slack channel IDs**. Canonical repo root on the Droplet is **`/opt/parking-acquisition-agents`** ([DROPLET_REPO_PATH.md](DROPLET_REPO_PATH.md)).

## Key-based login (laptop → Droplet)

1. On the Droplet, ensure your public key is in **`~/.ssh/authorized_keys`** for the user you use (`cursor` or `root`).
2. On your **Mac**, test without a password prompt:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@YOUR_DROPLET_IP 'echo ok'
```

Use the same user you configured in DigitalOcean / `~/.ssh/config`.

## `~/.ssh/config` (multiple projects / IPs)

Use a **separate `Host` block per Droplet** so `ssh parkinglot` and `ssh mobile-home-parks` never share the wrong IP.

**parkinglot** (this repo): `209.38.142.108`, user `root` — see [PROJECT-FACTS.md](PROJECT-FACTS.md) and [CURSOR-TWO-PROJECTS.md](CURSOR-TWO-PROJECTS.md).

```sshconfig
Host *
  AddKeysToAgent yes
  UseKeychain yes
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes

Host parkinglot parking-droplet
  HostName 209.38.142.108
  User cursor

Host mobile-home-parks
  HostName OTHER_PROJECT_IP
  User root
```

Test (no password prompt):

```bash
ssh -o BatchMode=yes parkinglot 'echo ok'
ssh -o BatchMode=yes mobile-home-parks 'echo ok'
```

**Cursor:** Command Palette → **Remote-SSH: Connect to Host…** → pick `parkinglot` (not a raw IP).

**Makefile / scripts:** `DROPLET=parkinglot ./scripts/sync-to-droplet.sh` works when `Host` name resolves via this file.

If `config` was missing, restore from `~/.ssh/config.broken` and fix each `HostName` to the current Droplet IP for that project.

## Rsync / repo sync from laptop

- Prefer **`./scripts/sync-to-droplet.sh`** with `DROPLET=…` and optional `REMOTE_PATH` / `SSH_USER` (see [OPERATIONS.md](OPERATIONS.md)).
- Or **`./scripts/sync-from-laptop-to-droplet.sh`** when copied to your laptop (see script header).

## CI / GitHub Actions

Deploy workflows use **`DROPLET_SSH_PRIVATE_KEY`** and related secrets; see [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).
