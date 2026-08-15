output "instance_name" {
  description = "Benchmark VM instance name."
  value       = google_compute_instance.benchmark.name
}

output "zone" {
  description = "Benchmark VM zone."
  value       = google_compute_instance.benchmark.zone
}

output "external_ip" {
  description = "Ephemeral external IP used for outbound access."
  value       = google_compute_instance.benchmark.network_interface[0].access_config[0].nat_ip
}

output "iap_ssh_command" {
  description = "Copy-paste command for SSH through Google IAP."
  value       = "gcloud compute ssh ${google_compute_instance.benchmark.name} --zone ${google_compute_instance.benchmark.zone} --tunnel-through-iap"
}
