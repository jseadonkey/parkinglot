# DigitalOcean Terraform

Creates:

- **Managed Postgres 16** (single node), database `parking_app`, and role **`parking_api`** (Terraform-managed password in state)
- **Database firewall** allowing only the application Droplet to reach the cluster
- **Spaces bucket** (private ACL) for contract drafts (S3-compatible)
- **Droplet** (Ubuntu 22.04) with Docker via cloud-init for 24/7 `docker compose`
- **Droplet firewall** allowing **SSH** (from `admin_ssh_source_cidrs`), **80**, and **443** only

Default **region** in `terraform.tfvars.example` is **`sfo3`** — closest DigitalOcean region to **Washington state** (there is no Seattle datacenter).

## Usage

1. [Create a DO API token](https://cloud.digitalocean.com/account/api/tokens) with read/write scope.
2. Choose a **globally unique** Spaces bucket name (lowercase, DNS-like).
3. Set **`droplet_ssh_keys`** to your DO SSH key IDs (required for normal SSH access).
4. Tighten **`admin_ssh_source_cidrs`** to your public IP `/32` (avoid leaving `0.0.0.0/0` on SSH in production).

### Spaces credentials for Terraform (required once)

Managing Spaces buckets and `digitalocean_spaces_key` requires **Spaces API credentials** in addition to the normal API token. [Create a Spaces key pair](https://cloud.digitalocean.com/account/api/spaces) in the control panel, then **export** them in the same shell before `terraform plan/apply`:

```bash
export SPACES_ACCESS_KEY_ID="..."
export SPACES_SECRET_ACCESS_KEY="..."
```

Terraform reads these automatically; do **not** commit them to `terraform.tfvars`. After apply, use **new** outputs `spaces_runtime_access_key` / `spaces_runtime_secret_key` for the application `deploy/.env` (least privilege to the drafts bucket).

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set spaces_bucket_name, optional ssh keys
export TF_VAR_do_token="dop_v1_..."
export SPACES_ACCESS_KEY_ID="..."
export SPACES_SECRET_ACCESS_KEY="..."
terraform init
terraform plan
terraform apply
```

Wire the application:

- Run `terraform output -raw database_url_sqlalchemy` and paste into `deploy/.env` as `DATABASE_URL` (includes `sslmode=require`).
- Enable **PostGIS** and **GRANT** the app user on `parking_app` (see [docs/GO-LIVE-WASHINGTON-DO.md](../../docs/GO-LIVE-WASHINGTON-DO.md)).
- Set `STORAGE_ENDPOINT` from `terraform output spaces_bucket_endpoint`, `STORAGE_BUCKET` from `terraform output spaces_bucket_name`, and `STORAGE_ACCESS_KEY` / `STORAGE_SECRET_KEY` from `terraform output -raw spaces_runtime_access_key` and `terraform output -raw spaces_runtime_secret_key` (Terraform-managed runtime key scoped to the drafts bucket).
- Follow [docs/GO-LIVE-WASHINGTON-DO.md](../../docs/GO-LIVE-WASHINGTON-DO.md) for DNS, Caddy TLS, and `docker compose -f deploy/docker-compose.production.yml`.
- Enable automated backups and monitoring in the DO UI for production.

**Note:** Managed DB firewall rules referencing a Droplet require the Droplet to exist; the first `terraform apply` creates both. If you prefer API-only (no Droplet), remove the Droplet and both firewall resources and manage DB access via trusted sources / VPN.

**State file security:** Terraform state contains database and Spaces secrets. Use a [remote backend](https://developer.hashicorp.com/terraform/language/settings/backends) with encryption (e.g. S3 + KMS, Terraform Cloud) for anything beyond a solo dev experiment.

Example backend snippets (copy to `backend.tf`): [backend.tf.example](backend.tf.example).
