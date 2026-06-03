# Open parkinglot in Cursor (automatic Droplet connection)

Cursor **cannot** auto-connect to SSH when you use **File → Open Folder** on the Mac copy (`main · local`). Use the **workspace file** instead — it connects to the Droplet every time you open it.

## Recommended (one step)

**Double-click** either:

- **`Open Parkinglot on Droplet.command`** (in this repo), or  
- **`parkinglot-droplet.code-workspace`** (same repo root)

Cursor will SSH to host **`parkinglot`** and open **`/opt/workspaces/parkinglot`**.

Status bar should show something like **`SSH: parkinglot`**, not **`local`**.

## From Terminal

```bash
cd /Users/johnkey/parkinglot/parkinglot
./scripts/open-cursor-droplet.sh
```

Or:

```bash
cursor /Users/johnkey/parkinglot/parkinglot/parkinglot-droplet.code-workspace
```

Optional shell shortcut (add to `~/.zshrc`):

```bash
alias parkinglot-cursor='cursor /Users/johnkey/parkinglot/parkinglot/parkinglot-droplet.code-workspace'
```

Then run `parkinglot-cursor` whenever you start work.

## Desktop shortcut (optional)

A symlink may already exist on your Desktop:

- **Parkinglot (Droplet).code-workspace**

If not:

```bash
ln -sf "/Users/johnkey/parkinglot/parkinglot/parkinglot-droplet.code-workspace" \
  "$HOME/Desktop/Parkinglot (Droplet).code-workspace"
```

Pin that file in **File → Open Recent** for fastest access.

## Two projects

| Project | Workspace file | SSH host | Remote folder |
|---------|----------------|----------|---------------|
| parkinglot | `parkinglot-droplet.code-workspace` | `parkinglot` | `/opt/workspaces/parkinglot` |
| mobile-home-parks | (create similarly in that repo) | `mobile-home-parks` | `/opt/workspaces/mobile-home-parks` |

See [CURSOR-TWO-PROJECTS.md](CURSOR-TWO-PROJECTS.md).

## SSH must work first

```bash
ssh parkinglot 'cat /opt/workspaces/parkinglot/.droplet-project-id'
```

Should print `parkinglot`. Fix `~/.ssh/config` if that fails (see [CURSOR-TWO-PROJECTS.md](CURSOR-TWO-PROJECTS.md)).

## Local clone (when to use it)

Keep the Mac folder for git/PRs only if you want. Day-to-day editing and deploys should use the **droplet workspace** so agents and terminals match production.
