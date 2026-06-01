# Stop the Agent from asking you to click “Allow”

The Agent asks for approval when **Run Mode** is set to approve each command. This repo is already configured so tests, git inspection, and common scripts can run automatically — you only need to flip one setting in Cursor.

## Step 1 — Turn on auto-run (required, one time)

1. Open **Cursor Settings** (`Cmd + ,`, then click **Cursor Settings** in the sidebar — not “VS Code Settings”).
   - Shortcut: `Cmd + Shift + J` (Agent settings).
2. Go to **Agents** → **Run Mode**.
3. Choose one:
   - **Auto-review** (recommended) — uses the allowlists below + smart pass-through for safe commands.
   - **Allowlist (with Sandbox)** — anything on the allowlist runs immediately; other commands may still prompt.
   - **Run Everything** — no prompts (fastest; use only if you trust the Agent fully).

**Do not** use a mode that asks every time (legacy “Ask every time” / strict manual approve).

4. Optional: under **Protection**, turn off **MCP Tool Protection** if MCP tools (Slack, Notion, etc.) still prompt after Step 1.

5. **Developer: Reload Window** (`Cmd + Shift + P` → type `Reload Window`) so Cursor reloads the JSON files below.

## Step 2 — What’s already configured (no action needed)

| File | What it does |
|------|----------------|
| `~/.cursor/permissions.json` | Your Mac: `git`, `pytest`, `python`, `docker`, `gh`, `curl`, `bash`, etc. |
| `.cursor/permissions.json` | This repo: `./scripts/run-api-tests.sh`, `pytest`, `docker compose`, `alembic`, `gh`, read-only git |
| `~/.cursor/sandbox.json` | Network allowed in sandbox (installs, curl, gh) |
| `.cursor/sandbox.json` | Same for this repo |

Together, the Agent can run things like:

```bash
make run-api-tests
git status
docker compose -f deploy/docker-compose.production.ghcr.yml ps
gh run list
```

without you clicking **Allow** each time.

## If you still see “Allow” once in a while

- Click **Add to allowlist** on that prompt — Cursor remembers it (unless Run Mode uses only `permissions.json`, in which case add the command prefix to `.cursor/permissions.json` and reload).
- **git push**, some **ssh** deploy steps, or commands that request **full machine access** may still prompt — that is intentional for production safety.
- Confirm you opened the **parkinglot** folder as the workspace (so `.cursor/permissions.json` applies).

## Tighten security later

Edit `~/.cursor/permissions.json` or `.cursor/permissions.json` and remove prefixes you do not want, or switch Run Mode back to **Allowlist** with a smaller list.

Official docs: [permissions.json](https://cursor.com/docs/reference/permissions), [Terminal / Run Mode](https://cursor.com/docs/agent/tools/terminal).
