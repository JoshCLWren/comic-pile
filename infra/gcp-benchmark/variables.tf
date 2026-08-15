variable "project_id" {
  description = "Google Cloud project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "GCP region for the benchmark VM and subnet."
  type        = string
  default     = "us-east1"
}

variable "zone" {
  description = "GCP zone for the benchmark VM. Keep this inside var.region."
  type        = string
  default     = "us-east1-b"
}

variable "instance_name" {
  description = "Compute Engine instance name."
  type        = string
  default     = "comicpile-benchmark"
}

variable "machine_type" {
  description = "Compute Engine machine type used for the benchmark."
  type        = string
  default     = "e2-micro"
}

variable "boot_disk_size_gb" {
  description = "Standard persistent boot disk size in GB."
  type        = number
  default     = 10
}

variable "repo_url" {
  description = "ComicPile Git repository URL cloned by the startup script."
  type        = string
  default     = "https://github.com/JoshCLWren/comic-pile.git"
}

variable "repo_ref" {
  description = "Git branch or tag cloned by the startup script."
  type        = string
  default     = "main"
}
