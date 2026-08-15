terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

resource "google_project_service" "compute" {
  project            = var.project_id
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_network" "benchmark" {
  name                    = "comicpile-benchmark"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.compute]
}

resource "google_compute_subnetwork" "benchmark" {
  name          = "comicpile-benchmark-${var.region}"
  ip_cidr_range = "10.42.0.0/24"
  region        = var.region
  network       = google_compute_network.benchmark.id
}

resource "google_compute_firewall" "iap_ssh" {
  name    = "comicpile-benchmark-iap-ssh"
  network = google_compute_network.benchmark.name

  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["comicpile-benchmark"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_instance" "benchmark" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["comicpile-benchmark"]

  boot_disk {
    auto_delete = true

    initialize_params {
      image = "debian-cloud/debian-13"
      size  = var.boot_disk_size_gb
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.benchmark.id

    # Ephemeral external IP for outbound apt/GitHub/Neon access. Inbound traffic
    # is still limited by the IAP-only firewall rule above.
    access_config {}
  }

  # Use ordinary metadata rather than metadata_startup_script. The latter is
  # ForceNew in the Google provider, which makes harmless bootstrap iterations
  # replace the entire benchmark VM. GCE still recognizes the startup-script
  # metadata key and runs it on boot, while Terraform can update it in place.
  metadata = {
    startup-script = templatefile("${path.module}/bootstrap.sh.tftpl", {
      repo_url = var.repo_url
      repo_ref = var.repo_ref
    })
  }

  depends_on = [
    google_compute_firewall.iap_ssh,
    google_project_service.compute,
  ]
}
