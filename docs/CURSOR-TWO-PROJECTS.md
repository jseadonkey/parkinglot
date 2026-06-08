# Two projects at once (parkinglot + mobile-home-parks)

Use **two Cursor windows** on the **Droplets** (Remote SSH). You do **not** need a `mobile-home-parks` folder on your Mac.

See [DROPLET-FIRST-WORKFLOW.md](DROPLET-FIRST-WORKFLOW.md) for what exists today on GitHub and each server.

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

| Window | Remote-SSH host | Open folder **on server** |
|--------|-----------------|---------------------------|
| **A — parkinglot** | **`parkinglot`** | `/opt/workspaces/parkinglot` |
| **B — mobile-home-parks** | **`mobile-home-parks`** | `/opt/workspaces/mobile-home-parks` |

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

The mobile-home-parks repo should have its own **`deploy/droplet.target`** created inside that repo, using that project’s host, IP, path, and project marker. Do not keep mobile-home-parks deploy target examples or bootstrap scripts in this parkinglot repo.

## 4. Server marker (one-time per Droplet path)

On the **parkinglot** Droplet:

```bash
./scripts/install-droplet-project-marker.sh
```

On **mobile-home-parks** (from that repo, after it has its own `deploy/droplet.target`):

```bash
./scripts/install-droplet-project-marker.sh
```

That writes `.droplet-project-id` so a mistaken rsync path is rejected.

## 5. What agents must do

- Deploy/sync only via **`make droplet-sync`** or **`./scripts/sync-to-droplet.sh`** (not hand-rolled `rsync` to an IP).
- Never change **`deploy/droplet.target`** to match a convenient IP — change **`~/.ssh/config`** instead if DNS/IP moves.
- If the user asks to deploy “to the droplet”, assume **`parkinglot`** only when this workspace is **`parkinglot`**.

See also [AGENT-DROPLET-SSH.md](AGENT-DROPLET-SSH.md).
