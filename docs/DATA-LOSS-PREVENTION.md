# Data / code loss prevention (2026-07-19)

## What kept erasing good work

Four independent processes were fighting each other:

1. **Mac → Droplet sync** (`scripts/sync-to-droplet.sh`) used `rsync --delete`.
   A stale Mac clone silently deleted newer Droplet-only files.
2. **GitHub Actions deploy** (`.github/workflows/deploy-droplet.yml`) used the
   same `rsync --delete` pattern from the Actions runner. Every push to `main`
   remirrored the runner checkout over the Droplet tree.
3. **Droplet auto-commit** staged multi-hundred-MB GIS caches (`data/king/`,
   `data/wa/`, …). GitHub rejects blobs >100 MB, so every push to `origin/main`
   failed. The Droplet drifted hundreds of commits ahead of GitHub with no
   off-site backup.
4. **Address-health cron installer** filtered for
   `address_health_agent.py` but the installed line used
   `run-address-health-agent-droplet.sh`, so every deploy appended a duplicate
   cron entry (28 copies by mid-July).

## Fixes in place

| Guard | Where |
|---|---|
| No `rsync --delete`; abort if Droplet is dirty or ahead of Mac | `scripts/sync-to-droplet.sh` |
| No `rsync --delete`; exclude `data/` from CI deploy | `.github/workflows/deploy-droplet.yml` |
| GIS caches gitignored + unstaged by auto-commit | `.gitignore`, `scripts/droplet-auto-commit.sh` |
| Snapshot-branch fallback if `main` push fails | `scripts/droplet-auto-commit.sh` → `droplet-snapshot` |
| Cron installer filter matches the real line + dedupes | `scripts/droplet-operator-agents-install.sh` |
| Alembic 0016–0019 restored (DB is stamped `20260714_0019`) | `services/api/alembic/versions/` |

## Source of truth

- **Code**: Droplet working tree at `/opt/workspaces/parkinglot`, mirrored to
  `origin/main` (and `origin/droplet-snapshot` as a safety net).
- **Secrets / production data**: `deploy/.env` on the Droplet only.
- **Rebuildable GIS caches**: under `data/{king,snohomish,kitsap,thurston,wa}/`
  — never commit these.

## If something looks “reverted”

1. Check whether a Mac sync or GitHub deploy just ran.
2. Prefer `git pull` on the Droplet over any mirror sync.
3. Use `FORCE_DROPLET_SYNC=1` only when you intentionally want to overwrite.
