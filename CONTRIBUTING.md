# Contributing

## Local development

1. Install [Docker](https://docs.docker.com/get-docker/) with Compose v2.
2. From the repo root: `docker compose up --build` (or `make local`).
3. API docs: http://localhost:8000/docs  
4. Sample ingest: `curl -X POST http://localhost:8000/internal/ingest/sample`  
5. Approval UI: http://localhost:3000

Python **3.12** matches the production Docker image.

## CI

Pull requests run [`.github/workflows/ci.yml`](.github/workflows/ci.yml): Docker builds for API + UI, and `docker compose config` validation using [`deploy/ci.env`](deploy/ci.env).

Slack (optional): [docs/SLACK.md](docs/SLACK.md) · [`scripts/set-slack-env-local.sh`](scripts/set-slack-env-local.sh) (dev `.env`) · [`scripts/set-slack-env-on-droplet.sh`](scripts/set-slack-env-on-droplet.sh) (Droplet `deploy/.env`).

## Style

Match existing patterns in each package; keep changes focused on one concern per pull request.

## License

See [LICENSE](LICENSE) (MIT).
