# Droplet repository path (single canonical location)

Use **one path** on the Droplet for every command, script default, and doc example:

## **`/opt/parking-acquisition-agents`**

That is the **default** in:

- [deploy/README.md](../deploy/README.md) (production compose)
- GitHub Actions (`DROPLET_REMOTE_PATH` defaults here when unset)
- `REMOTE_PATH` in [`scripts/remote-rebuild.sh`](../scripts/remote-rebuild.sh), [`scripts/set-slack-env-on-droplet.sh`](../scripts/set-slack-env-on-droplet.sh), and related helpers
- Operator docs ([OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md), [OPERATIONS.md](OPERATIONS.md))

---

## If your clone lives somewhere else today

Some hosts still have the repo only under **`/opt/workspaces/parkinglot`**. Pick **one** approach:

### Option A — Symlink (recommended if `/opt/parking-acquisition-agents` does not exist yet)

On the Droplet:

```bash
sudo mkdir -p /opt
sudo ln -sfn /opt/workspaces/parkinglot /opt/parking-acquisition-agents
```

Then **`cd /opt/parking-acquisition-agents`** always lands in your tree.

**Do not** run this if `/opt/parking-acquisition-agents` is already a **real directory** with a different clone — resolve manually or use Option B.

### Option B — Environment variables (no symlink)

Set **`REMOTE_PATH`** / **`DROPLET_REMOTE_PATH`** to your actual path whenever you sync or run Actions:

```bash
REMOTE_PATH=/opt/workspaces/parkinglot DROPLET=YOUR_IP ./scripts/sync-to-droplet.sh
```

GitHub: repository variable **`DROPLET_REMOTE_PATH`** = `/opt/workspaces/parkinglot`.

---

## Verify

```bash
cd /opt/parking-acquisition-agents && git rev-parse --show-toplevel
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env config --quiet && echo OK
```

After editing **`deploy/.env`**, check for placeholder **`PUBLIC_API_URL`** / **`example.com`** hosts:

```bash
python3 scripts/check_deploy_env_warnings.py
```
