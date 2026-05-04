# One file for real secrets (Droplet or laptop)

**Goal:** edit **`deploy/secrets.env`** (one gitignored file) instead of hunting through a long `deploy/.env`.

**How it works**

1. Committed template: **`deploy/env.production.example`**
2. Your overrides: **`deploy/secrets.env`** (create from [`secrets.env.example`](secrets.env.example), never commit)
3. Run the renderer; it merges **base + secrets** (secrets win) and writes **`deploy/.env`**

```bash
cp deploy/secrets.env.example deploy/secrets.env
# edit deploy/secrets.env with real tokens / DATABASE_URL / etc.
make render-deploy-env
# or: python3 scripts/render_deploy_env.py
```

Keys you set only in `secrets.env` are appended at the bottom of `deploy/.env` under a short comment. Keys that also exist in the example file keep their line order and section comments from the example.

**Checks**

- `python3 scripts/render_deploy_env.py --dry-run` — print the merge without writing
- `make render-deploy-env-check` or `python3 scripts/render_deploy_env.py --check` — after write, exit non-zero if required URL keys look empty or still contain placeholders

**`scripts/droplet_set_database_url.py`**

That script updates **`DATABASE_URL` directly in `deploy/.env`**. If you use the secrets workflow, copy the new `DATABASE_URL` into **`deploy/secrets.env`** (or set it there first and re-run the renderer) so the next `make render-deploy-env` does not bring back an old value from the example file.

**Switching to a new Postgres cluster (DigitalOcean Managed)**

1. In the DO control panel, copy the **new** connection URI for the same logical user/database you intend to use (host looks like **`*.db.ondigitalocean.com`**, port **25060**, **`sslmode=require`**). Convert to **`postgresql+psycopg://`** if needed (see **`scripts/droplet_paste_database_uri.py`**).
2. Put **one** line in **`deploy/secrets.env`**:  
   `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@NEW_HOST:25060/DATABASE?sslmode=require`
3. Regenerate and restart so **api**, **worker**, and **beat** all load it:  
   `python3 scripts/render_deploy_env.py`  
   `docker compose -f deploy/docker-compose.production.yml --env-file deploy/.env up -d`
4. Confirm the URL in use (hostname only is enough):  
   `grep '^DATABASE_URL=' deploy/.env` — it must **not** contain **`@postgres:`** (that is the optional **local** PostGIS container, not Managed Postgres).
5. **Firewall:** in **Databases → Trusted sources**, allow your **Droplet** (or its IP) on the **new** cluster.
6. If you use **GitHub Actions** with repository secret **`DEPLOY_DATABASE_URL`**, update that secret to the **new** URI so future automation does not push the old URL.
7. Repo root **`.env`** / **`docker-compose.yml`** (local dev with a **`postgres`** container) are **not** production — they do not change what the Droplet uses.

**If `deploy/secrets.env` is missing**

The renderer still runs: output is the example file only, with a note on stderr to create `secrets.env` when you are ready.
