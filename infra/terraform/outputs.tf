output "database_host" {
  value       = digitalocean_database_cluster.postgres.host
  description = "Managed Postgres hostname (private URI available in DO control panel)."
}

output "database_port" {
  value = digitalocean_database_cluster.postgres.port
}

output "spaces_bucket_endpoint" {
  value       = "https://${var.region}.digitaloceanspaces.com"
  description = "S3-compatible endpoint for Spaces (set STORAGE_ENDPOINT / AWS_ENDPOINT_URL_S3)."
}

output "spaces_bucket_name" {
  value = digitalocean_spaces_bucket.drafts.name
}

output "spaces_runtime_access_key" {
  value       = digitalocean_spaces_key.app_runtime.access_key
  sensitive   = true
  description = "STORAGE_ACCESS_KEY in deploy/.env (read/write on drafts bucket only)."
}

output "spaces_runtime_secret_key" {
  value       = digitalocean_spaces_key.app_runtime.secret_key
  sensitive   = true
  description = "STORAGE_SECRET_KEY in deploy/.env."
}

output "droplet_ipv4" {
  value       = digitalocean_droplet.app.ipv4_address
  description = "Public IPv4 for SSH and Docker Compose / Traefik deployment."
}

output "database_app_user" {
  value       = digitalocean_database_user.app.name
  description = "Application database role created by Terraform."
}

output "database_url_sqlalchemy" {
  value       = "postgresql+psycopg://${digitalocean_database_user.app.name}:${digitalocean_database_user.app.password}@${digitalocean_database_cluster.postgres.host}:${digitalocean_database_cluster.postgres.port}/parking_app?sslmode=require"
  sensitive   = true
  description = "Paste into deploy/.env as DATABASE_URL (keep secret)."
}
