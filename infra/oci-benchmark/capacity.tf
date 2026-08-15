data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

locals {
  # Probe a useful range of Always Free-compatible A1 allocations in one pass.
  # This is a point-in-time capacity query only; it does not reserve or launch
  # compute. Larger configurations come first so the output is easy to scan.
  a1_capacity_sizes = [
    { label = "2cpu-12gb", ocpus = 2, memory_in_gbs = 12 },
    { label = "2cpu-6gb", ocpus = 2, memory_in_gbs = 6 },
    { label = "1cpu-12gb", ocpus = 1, memory_in_gbs = 12 },
    { label = "1cpu-8gb", ocpus = 1, memory_in_gbs = 8 },
    { label = "1cpu-6gb", ocpus = 1, memory_in_gbs = 6 },
    { label = "1cpu-4gb", ocpus = 1, memory_in_gbs = 4 },
    { label = "1cpu-2gb", ocpus = 1, memory_in_gbs = 2 },
  ]

  a1_capacity_checks = {
    for check in flatten([
      for ad in data.oci_identity_availability_domains.all.availability_domains : [
        for size in local.a1_capacity_sizes : {
          key           = "${ad.name}|${size.label}"
          ad_name       = ad.name
          label         = size.label
          ocpus         = size.ocpus
          memory_in_gbs = size.memory_in_gbs
        }
      ]
    ]) : check.key => check
  }
}

# OCI exposes a capacity-report API specifically so callers can check whether a
# requested shape/config can be launched before attempting to create an
# instance. These reports do not reserve capacity or launch compute.
resource "oci_core_compute_capacity_report" "a1_matrix" {
  for_each = local.a1_capacity_checks

  availability_domain = each.value.ad_name
  compartment_id      = var.tenancy_ocid

  shape_availabilities {
    instance_shape = var.shape

    instance_shape_config {
      ocpus         = each.value.ocpus
      memory_in_gbs = each.value.memory_in_gbs
    }
  }
}

output "a1_capacity_matrix" {
  description = "Point-in-time A1 host-capacity matrix across all Ashburn ADs and useful Always Free-compatible sizes."
  value = {
    for ad in data.oci_identity_availability_domains.all.availability_domains :
    ad.name => {
      for size in local.a1_capacity_sizes :
      size.label => {
        availability_status = oci_core_compute_capacity_report.a1_matrix["${ad.name}|${size.label}"].shape_availabilities[0].availability_status
        available_count     = oci_core_compute_capacity_report.a1_matrix["${ad.name}|${size.label}"].shape_availabilities[0].available_count
        ocpus               = size.ocpus
        memory_in_gbs       = size.memory_in_gbs
      }
    }
  }
}
