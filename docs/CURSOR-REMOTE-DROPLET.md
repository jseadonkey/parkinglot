# Use Cursor on the Droplet (Remote SSH)

You cannot move **this chat thread** onto the Droplet — Cursor conversations stay in Cursor. You *can* open the **repo on the Droplet** as your workspace so the agent’s **files and terminal** run **on the server** instead of only proxying `ssh` from your Mac.

## What this improves

- **Operations:** `docker compose`, logs, edits under `/opt/…` run locally on the Droplet from the integrated terminal.
- **Fewer “run SSH for me” steps:** The agent uses the **remote** shell and file tree by default.

## What it does *not* change

- Cursor still sends relevant **code/context** to the AI provider for answers (same as any Cursor project). It is not a fully air‑gapped “local only” model unless you configure a local model / enterprise setup separately.
- You still need **network** from your laptop to the Droplet (and usually outbound HTTPS for Cursor).

## Setup (high level)

1. Install **OpenSSH** server on the Droplet (Ubuntu images already have `sshd`).
2. On your **Mac**, ensure you can run:  
   `ssh -o BatchMode=yes root@YOUR_PUBLIC_IP 'echo ok'`
3. In **Cursor**: Command Palette → **“Remote-SSH: Connect to Host…”** (same idea as VS Code Remote SSH). Pick `root@YOUR_PUBLIC_IP` or an entry from `~/.ssh/config` (see [AGENT-DROPLET-SSH.md](AGENT-DROPLET-SSH.md)).
4. After connected, **File → Open Folder** on the remote host, e.g.  
   **`/opt/workspaces/parkinglot`**  
   (see [PROJECT-FACTS.md](PROJECT-FACTS.md) for the canonical path and IDs).

Then start a **new chat** in that remote window; ask the agent to use the **remote** terminal for `docker compose`, migrations, and Slack checks.

## Handoff notes on the server

- **Canonical operator facts:** `docs/PROJECT-FACTS.md` in the repo (same path on the Droplet under `/opt/workspaces/parkinglot`).
- Older example: **`/root/parking-handoff/TEAM-NOTES.txt`** (if present).

## If Remote SSH is not available in Cursor

Use **VS Code with Remote SSH** for server-side editing, or keep using **plain SSH** from the Mac terminal and ask the agent to run `ssh …` commands (works when `BatchMode` and keys are set up as in [AGENT-DROPLET-SSH.md](AGENT-DROPLET-SSH.md)).
