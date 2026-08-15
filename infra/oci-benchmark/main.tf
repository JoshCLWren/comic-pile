terraform {
  required_version = ">= 1.6.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "8.23.0"
    }
  }
}

provider "oci" {
  config_file_profile = var.oci_profile
  region              = var.region
}

data "oci_identity_availability_domain" "benchmark" {
  compartment_id = var.tenancy_ocid
  ad_number      = var.availability_domain_number
}

data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = var.shape
  state                    = "AVAILABLE"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "benchmark" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.43.0.0/16"]
  display_name   = "comicpile-benchmark"
  dns_label      = "comicpilebench"
}

resource "oci_core_internet_gateway" "benchmark" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.benchmark.id
  display_name   = "comicpile-benchmark"
  enabled        = true
}

resource "oci_core_route_table" "benchmark" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.benchmark.id
  display_name   = "comicpile-benchmark-public"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.benchmark.id
  }
}

resource "oci_core_security_list" "benchmark" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.benchmark.id
  display_name   = "comicpile-benchmark"

  ingress_security_rules {
    protocol = "6"
    source   = var.ssh_source_cidr

    tcp_options {
      min = 22
      max = 22
    }
  }

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_subnet" "benchmark" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.benchmark.id
  cidr_block                 = "10.43.1.0/24"
  display_name               = "comicpile-benchmark"
  dns_label                  = "api"
  route_table_id             = oci_core_route_table.benchmark.id
  security_list_ids          = [oci_core_security_list.benchmark.id]
  prohibit_public_ip_on_vnic = false
}

resource "oci_core_instance" "benchmark" {
  availability_domain = data.oci_identity_availability_domain.benchmark.name
  compartment_id      = var.compartment_ocid
  display_name        = var.instance_name
  shape               = var.shape

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_in_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.benchmark.id
    assign_public_ip = true
    hostname_label   = "comicpile"
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_size_gb
  }

  metadata = {
    ssh_authorized_keys = file(pathexpand(var.ssh_public_key_path))
    user_data = base64encode(templatefile("${path.module}/bootstrap.sh.tftpl", {
      repo_url = var.repo_url
      repo_ref = var.repo_ref
    }))
  }
}

data "oci_core_vnic_attachments" "benchmark" {
  compartment_id = var.compartment_ocid
  instance_id    = oci_core_instance.benchmark.id
}

data "oci_core_vnic" "benchmark" {
  vnic_id = data.oci_core_vnic_attachments.benchmark.vnic_attachments[0].vnic_id
}
