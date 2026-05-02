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

## `~/.ssh/config` snippet (example)

```sshconfig
Host parking-droplet
  HostName YOUR_DROPLET_IP
  User root
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
```

Then: `ssh -o BatchMode=yes parking-droplet 'echo ok'`

## Rsync / repo sync from laptop

- Prefer **`./scripts/sync-to-droplet.sh`** with `DROPLET=…` and optional `REMOTE_PATH` / `SSH_USER` (see [OPERATIONS.md](OPERATIONS.md)).
- Or **`./scripts/sync-from-laptop-to-droplet.sh`** when copied to your laptop (see script header).

## CI / GitHub Actions

Deploy workflows use **`DROPLET_SSH_PRIVATE_KEY`** and related secrets; see [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).
