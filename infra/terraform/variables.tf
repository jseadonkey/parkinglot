variable "do_token" {
  type        = string
  description = "DigitalOcean API token (set via TF_VAR_do_token or terraform.tfvars, never commit secrets)."
  sensitive   = true
}

variable "region" {
  type        = string
  description = "DigitalOcean region slug. Closest to Washington state is sfo3 or sfo2 (no Seattle DC)."
  default     = "sfo3"
}

variable "project_name" {
  type        = string
  description = "Prefix for created resources."
  default     = "parking-acquisition"
}

variable "db_size_slug" {
  type        = string
  description = "Managed Postgres node size."
  default     = "db-s-1vcpu-1gb"
}

variable "spaces_bucket_name" {
  type        = string
  description = "Globally unique Spaces bucket for contract drafts."
}

variable "droplet_ssh_keys" {
  type        = list(string)
  description = "SSH key fingerprints or IDs to install on the compute Droplet (required for practical SSH access)."
  default     = []
}

variable "admin_ssh_source_cidrs" {
  type        = list(string)
  description = "CIDR blocks allowed to reach SSH (port 22) on the Droplet. Restrict to your home/office IP /32 for production."
  default     = ["0.0.0.0/0", "::/0"]
}
