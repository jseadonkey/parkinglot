# Two projects at once (parkinglot + mobile-home-parks)

Use **two Cursor windows** and **never type a raw IP** when syncing or deploying. Each repo and each Droplet has a fixed name.

## 1. SSH aliases (your Mac — `~/.ssh/config`)

| Cursor / terminal name | IP | Use for |
|----------------------|-----|---------|
| **`parkinglot`** | `209.38.142.108` | This repo only |
| **`mobile-home-parks`** | `134.199.209.177` | mobile-home-parks repo only |

Test:

```bash
ssh parkinglot 'hostname; cat /opt/workspaces/parkinglot/.droplet-project-id 2>/dev/null || echo no-marker'
ssh mobile-home-parks 'hostname; cat /opt/workspaces/mobile-home-parks/.droplet-project-id 2>/dev/null || echo no-marker'
```

## 2. Two Cursor windows (recommended)

| Window | Open folder (local) | Optional Remote-SSH |
|--------|---------------------|---------------------|
| **A — parkinglot** | `~/parkinglot/parkinglot` (this repo) | Connect to host **`parkinglot`**, folder `/opt/workspaces/parkinglot` |
| **B — mobile-home-parks** | Your `mobile-home-parks` clone | Connect to host **`mobile-home-parks`**, folder that project’s path on that server |

Rules:

- **Do not** use the other project’s SSH host in this window.
- **Do not** set `DROPLET=134.199...` while in the parkinglot folder (scripts will **abort**).
- Prefer **`make droplet-sync`** here — it reads **`deploy/droplet.target`** automatically.

## 3. Repo lock file (`deploy/droplet.target`)

This repo ships:

```ini
project_id=parkinglot
ssh_host=parkinglot
ssh_user=root
allowed_hostname=209.38.142.108
remote_path=/opt/workspaces/parkinglot
```

**`scripts/sync-to-droplet.sh`** and **`scripts/remote-rebuild.sh`**:

1. Resolve `ssh_host` → must equal `allowed_hostname`.
2. Read **`.droplet-project-id`** on the server — must equal `project_id`.

Copy **`deploy/droplet.target.example.mobile-home-parks`** into the other repo as **`deploy/droplet.target`** with that project’s values.

## 4. Server marker (one-time per Droplet path)

On the **parkinglot** Droplet:

```bash
./scripts/install-droplet-project-marker.sh
```

On **mobile-home-parks** (from that repo, after you add `deploy/droplet.target` there):

```bash
./scripts/install-droplet-project-marker.sh
```

That writes `.droplet-project-id` so a mistaken rsync path is rejected.

## 5. What agents must do

- Deploy/sync only via **`make droplet-sync`** or **`./scripts/sync-to-droplet.sh`** (not hand-rolled `rsync` to an IP).
- Never change **`deploy/droplet.target`** to match a convenient IP — change **`~/.ssh/config`** instead if DNS/IP moves.
- If the user asks to deploy “to the droplet”, assume **`parkinglot`** only when this workspace is **`parkinglot`**.

See also [AGENT-DROPLET-SSH.md](AGENT-DROPLET-SSH.md).
