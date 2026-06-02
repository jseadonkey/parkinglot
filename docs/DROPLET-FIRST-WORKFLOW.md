# Work on the Droplet (not your Mac)

You do **not** need a full copy of every project on your Mac. Use **Cursor Remote SSH** so code, git, and Docker all live on the server.

## What you have today

| Project | GitHub | Mac folder | Droplet | IP (SSH name) |
|---------|--------|------------|---------|----------------|
| **parkinglot** | [github.com/jseadonkey/parkinglot](https://github.com/jseadonkey/parkinglot) | Optional: `~/parkinglot/parkinglot` (for this chat) | **Yes** — `/opt/workspaces/parkinglot` | `parkinglot` → `209.38.142.108` |
| **mobile-home-parks** | [github.com/jseadonkey/mobile-home-parks](https://github.com/jseadonkey/mobile-home-parks) | **None** (not required) | **Yes** — `/opt/workspaces/mobile-home-parks` (README starter) | `mobile-home-parks` → `134.199.209.177` |

These are **two different DigitalOcean Droplets**. Parkinglot must never be synced to `134.199.209.177`.

On the parkinglot server, `/opt/workspaces/hotel-sales` is only a **CSV folder**, not the mobile-home-parks app.

## parkinglot — already on GitHub

- Repo: **https://github.com/jseadonkey/parkinglot**
- Production code on Droplet: **`/opt/workspaces/parkinglot`**
- Deploy uses GitHub Actions + `git pull` on the server (see [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md))

### Cursor window 1 (parkinglot)

1. Command Palette → **Remote-SSH: Connect to Host…** → **`parkinglot`**
2. **File → Open Folder** → **`/opt/workspaces/parkinglot`**
3. New chat in **that** window — agent runs commands on the server

You can keep a small Mac clone only for Cursor Cloud Agent if you like; day-to-day edits happen on the Droplet.

### Pull latest on the parkinglot Droplet

```bash
ssh parkinglot
cd /opt/workspaces/parkinglot
git fetch origin
git checkout main
git pull origin main
```

(Use your real branch name if you deploy from a feature branch.)

## mobile-home-parks — not on Mac yet

There is **no** `mobile-home-parks` folder on your Mac and **no** GitHub repo under your account yet (as of last check).

To start the project **on the server only**:

1. Create GitHub repo (once): **Actions** or ask the agent to run `gh repo create mobile-home-parks`.
2. On the **mobile-home-parks** Droplet:

```bash
ssh mobile-home-parks
mkdir -p /opt/workspaces/mobile-home-parks
cd /opt/workspaces/mobile-home-parks
git clone git@github.com:jseadonkey/mobile-home-parks.git .
echo mobile-home-parks > .droplet-project-id
```

3. Cursor window 2: Remote-SSH → **`mobile-home-parks`** → open **`/opt/workspaces/mobile-home-parks`**

Or run from parkinglot repo (after GitHub repo exists):

```bash
./scripts/bootstrap-mobile-home-parks-droplet.sh
```

## Safety (parkinglot)

From the **parkinglot** tree only:

```bash
make droplet-sync   # refuses wrong IP — see deploy/droplet.target
```

See [CURSOR-TWO-PROJECTS.md](CURSOR-TWO-PROJECTS.md).
