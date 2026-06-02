# DigitalOcean capacity review

Snapshot from production checks (Droplet SSH + compose). Re-run **Actions → Droplet resources (via Droplet)** for fresh numbers.

## Current Droplet (209.38.142.108)

| Signal | Observed | Notes |
|--------|----------|--------|
| Hostname | `ubuntu-s-1vcpu-2gb-sfo3` | Name is stale — do not trust it for sizing |
| RAM (actual) | **~8 GiB** total, **~1.8 GiB** used | Likely resized to a larger plan already |
| CPUs | **4** | Enough for api + 2 workers + beat |
| Load | **~0.4–0.5** (after queue purge) | Was **>2** when Celery backlog was huge |
| Root disk | **48 GiB, ~71% used** (~34 GiB) | Getting tight — Docker images + data |
| Block volume | **100 GiB at `/mnt/volume_sfo3_*`, 0% used** | Use this for heavy data / Docker |
| Swap | **None** | OOM during spikes → DO “run failed” / killed containers |

### Container RAM (steady state, post-purge)

| Service | ~RAM |
|---------|------|
| Redis | 330 MiB (was **1+ GiB** with 600k queued tasks) |
| worker (parking) | 260 MiB |
| worker-slack | 130 MiB |
| api / beat | ~95 MiB each |
| UIs + caddy | ~100 MiB combined |

**Peak risk:** `worker` with `--concurrency=4` running pipelines + large Redis queue + Postgres connections can still spike past available RAM with **no swap**.

## Managed Postgres (terraform default)

Repo Terraform (`infra/terraform/main.tf`) defaults to:

- **`db-s-1vcpu-1gb`** — 1 GiB RAM, ~22 backend connections, 10 GiB storage (~$15/mo)

That is tight for production if the live cluster matches: scoring queries, operator stats, and Celery all hit Postgres.

## Does an upgrade make sense?

**Yes — for stability, not because the site is slow right now.**

| Resource | Recommendation | Why | Rough cost delta |
|----------|----------------|-----|------------------|
| **Droplet** | Stay on **≥ 4 vCPU / 8 GiB** (`s-4vcpu-8gb` or current size if already there) | Matches what you are actually running; avoid going back to 2 GiB | ~$48/mo if not already |
| **Droplet disk** | Move Docker/data to **100 GiB volume** or grow root disk | Root at **71%** causes deploy/pull failures | Volume already paid; or +$10–20/mo disk |
| **Redis** | Cap at **512 MiB** (`maxmemory` in compose) | Prevents Redis alone taking 1+ GiB | Free |
| **Postgres** | Upgrade to **`db-s-1vcpu-2gb`** minimum; **`db-s-2vcpu-4gb`** if heavy analytics | More RAM + connections (47 / 97) | +$15–45/mo vs 1 GiB plan |
| **Celery** | Keep **`SCHEDULED_ENQUEUE_UNSCORED_ENABLED=false`** until stable | Stops refilling 100k+ task backlogs | Free |

## “Run failed” from DigitalOcean — likely causes

1. **Out-of-memory (no swap)** — Celery backlog + Redis + workers on a small plan.
2. **Disk full** — root filesystem high 60s–70s% during `docker pull` / builds.
3. **Managed DB** — connection limit or memory on `db-s-1vcpu-1gb` under load.
4. **GitHub Actions deploy** — failed image pull (not DO droplet CPU); different from DO alerts.

Check **DigitalOcean → Activity** and **Monitoring → Insights** on the Droplet and DB cluster for the exact event type.

## GitHub: DO API workflows

Add repository secret **`DO_TOKEN`** (read-only) to run:

- **DO — list Droplets** — size, vCPUs, RAM
- **DO — fetch Postgres connection hints** — cluster size / status

## Next steps (operator)

1. In DO control panel: confirm **Droplet plan size** and **database cluster size** match tables above.
2. Apply compose change (Redis `maxmemory`) and redeploy.
3. Optionally mount block storage for `/var/lib/docker` or `data/` (see DO docs “Mount a volume”).
4. Upgrade Postgres to **2 GiB** if still on 1 GiB.
5. Re-enable pipeline auto-enqueue only in small batches after watchdog stays green.
