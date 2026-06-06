# Droplet repository path (single canonical location)

Use **one path** on the Droplet for every command, script default, and doc example:

## **`/opt/workspaces/parkinglot`**

That is the **default** in:

- [deploy/README.md](../deploy/README.md) (production compose)
- GitHub Actions (`DROPLET_REMOTE_PATH` defaults here when unset)
- `REMOTE_PATH` in [`scripts/remote-rebuild.sh`](../scripts/remote-rebuild.sh), [`scripts/set-slack-env-on-droplet.sh`](../scripts/set-slack-env-on-droplet.sh), and related helpers
- Operator docs ([OPERATOR-TODO-BUNDLE.md](OPERATOR-TODO-BUNDLE.md), [OPERATIONS.md](OPERATIONS.md))

---

## If the clone moves

Update **`deploy/droplet.target`** first, then align GitHub variable
**`DROPLET_REMOTE_PATH`** to the same value. The deploy scripts validate that
the configured path belongs to the parkinglot project before syncing or
rebuilding.

```bash
REMOTE_PATH=/opt/workspaces/parkinglot DROPLET=209.38.142.108 ./scripts/sync-to-droplet.sh
```

GitHub: repository variable **`DROPLET_REMOTE_PATH`** = `/opt/workspaces/parkinglot`.

---

## Verify

```bash
cd /opt/workspaces/parkinglot && git rev-parse --show-toplevel
docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env config --quiet && echo OK
```

After editing **`deploy/.env`**, check for placeholder **`PUBLIC_API_URL`** / **`example.com`** hosts:

```bash
python3 scripts/check_deploy_env_warnings.py
```
