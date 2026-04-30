# ADR-001: Stack choices

## Context

Multi-agent parking acquisition with human approval gates, DigitalOcean deployment, single pilot region.

## Decision

- **Workers / API**: Python 3.12, FastAPI, SQLAlchemy 2, GeoAlchemy2, Celery, Redis.
- **Database**: PostgreSQL 16 + PostGIS (local via Docker; Managed DB on DO).
- **Object storage**: S3 API — MinIO locally, DigitalOcean Spaces in production.
- **Approval UI**: Next.js 15 (App Router), TypeScript, Tailwind CSS.
- **Orchestration**: Celery task chains encode the pipeline; human approval is a blocking state in DB polled by workflow tasks.
- **IaC**: Terraform for DigitalOcean resources.

## Consequences

- One shared Python package (`parking_core`) keeps API and worker aligned on Pydantic models.
- Temporal was deferred to reduce v1 operational complexity; Celery + explicit status columns remain auditable.
