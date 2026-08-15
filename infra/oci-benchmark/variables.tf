variable "oci_profile" {
  type        = string
  description = "OCI CLI/config profile name."
  default     = "DEFAULT"
}

variable "tenancy_ocid" {
  type        = string
  description = "OCI tenancy OCID. Prefer TF_VAR_tenancy_ocid from ~/.oci/config."
  sensitive   = true
}

variable "compartment_ocid" {
  type        = string
  description = "OCI compartment OCID. Defaults to the root tenancy when omitted via tfvars by setting it equal to tenancy_ocid."
}

variable "region" {
  type        = string
  description = "OCI region for the benchmark."
  default     = "us-ashburn-1"
}

variable "availability_domain_number" {
  type        = number
  description = "Availability domain number to use."
  default     = 1
}

variable "instance_name" {
  type    = string
  default = "comicpile-benchmark"
}

variable "shape" {
  type    = string
  default = "VM.Standard.A1.Flex"
}

variable "ocpus" {
  type    = number
  default = 2
}

variable "memory_in_gbs" {
  type    = number
  default = 6
}

variable "boot_volume_size_gb" {
  type    = number
  default = 50
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "ssh_source_cidr" {
  type        = string
  description = "CIDR allowed to SSH to the benchmark host. Use your public IP /32 when possible."
}

variable "repo_url" {
  type    = string
  default = "https://github.com/JoshCLWren/comic-pile.git"
}

variable "repo_ref" {
  type    = string
  default = "infra/gcp-fastapi-benchmark"
}
