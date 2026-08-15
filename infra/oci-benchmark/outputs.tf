output "instance_id" {
  value = oci_core_instance.benchmark.id
}

output "public_ip" {
  value = data.oci_core_vnic.benchmark.public_ip_address
}

output "ssh_command" {
  value = "ssh ubuntu@${data.oci_core_vnic.benchmark.public_ip_address}"
}

output "availability_domain" {
  value = data.oci_identity_availability_domain.benchmark.name
}

output "image_name" {
  value = data.oci_core_images.ubuntu.images[0].display_name
}
