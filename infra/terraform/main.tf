locals {
  name = var.project_name
}

resource "digitalocean_database_cluster" "postgres" {
  name       = "${local.name}-pg"
  engine     = "pg"
  version    = "16"
  size       = var.db_size_slug
  region     = var.region
  node_count = 1

  maintenance_window {
    day  = "sunday"
    hour = "09:00:00"
  }

  tags = ["parking-acquisition", "managed-db"]
}

resource "digitalocean_database_db" "app" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "parking_app"
}

resource "digitalocean_database_user" "app" {
  cluster_id = digitalocean_database_cluster.postgres.id
  name       = "parking_api"
}

resource "digitalocean_database_firewall" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id

  rule {
    type  = "droplet"
    value = digitalocean_droplet.app.id
  }
}

resource "digitalocean_spaces_bucket" "drafts" {
  name   = var.spaces_bucket_name
  region = var.region
  acl    = "private"
}

# Runtime key pair for the application (S3 API to this bucket only). Requires Spaces-capable
# credentials when running `terraform apply` (see infra/terraform/README.md).
resource "digitalocean_spaces_key" "app_runtime" {
  name = "${local.name}-app-runtime"

  grant {
    bucket     = digitalocean_spaces_bucket.drafts.name
    permission = "readwrite"
  }
}

resource "digitalocean_droplet" "app" {
  image    = "ubuntu-22-04-x64"
  name     = "${local.name}-app-1"
  region   = var.region
  size     = "s-2vcpu-4gb"
  ssh_keys = var.droplet_ssh_keys

  user_data = <<-EOT
    #cloud-config
    package_update: true
    packages:
      - ca-certificates
      - curl
    runcmd:
      - curl -fsSL https://get.docker.com | sh
      - usermod -aG docker root
  EOT

  tags = ["parking-acquisition", "compute"]
}

resource "digitalocean_firewall" "edge" {
  name        = "${local.name}-edge"
  droplet_ids = [digitalocean_droplet.app.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.admin_ssh_source_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
