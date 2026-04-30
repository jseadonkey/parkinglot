# Security

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security-sensitive reports. Contact the repository maintainers privately with reproduction steps and impact.

## Production hygiene

- **`GET /internal/tasks/{task_id}`** can return **exception tracebacks** on task failure. Keep **`INTERNAL_API_KEY`** set in production and treat this endpoint as operator-only (same trust boundary as other `/internal/*` routes).
- GitHub Actions workflows that call **`/internal/*` from the Droplet** use repository secret **`SLACK_DEPLOY_NOTIFY_INTERNAL_API_KEY`**. When set, it must **match** **`INTERNAL_API_KEY`** in the Droplet’s **`deploy/.env`** (rotate both together). See [`scripts/gh-set-slack-notify-internal-secret.sh`](scripts/gh-set-slack-notify-internal-secret.sh).
- **`SLACK_BOT_TOKEN`** grants the ability to post as the bot; store it only in `deploy/.env` (or your secret manager). Rotate if leaked. See [docs/SLACK.md](docs/SLACK.md).
- Rotate **`INTERNAL_API_KEY`**, **Spaces keys**, and **database credentials** periodically.
- Restrict **SSH** (`admin_ssh_source_cidrs` in Terraform) to known IPs.
- Store **Terraform state** in an encrypted remote backend ([`infra/terraform/backend.tf.example`](infra/terraform/backend.tf.example)).
- Treat **`deploy/.env`** on the Droplet as secret (never commit; rsync/GitHub Actions exclude it by design).

## Dependency updates

GitHub **Dependabot** is enabled for Actions ([`.github/dependabot.yml`](.github/dependabot.yml)). Review and merge updates regularly.
