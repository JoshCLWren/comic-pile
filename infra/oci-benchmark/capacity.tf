data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

# OCI exposes a capacity-report API specifically so callers can check whether a
# requested shape/config can be launched before attempting to create an
# instance. Keep this separate from the benchmark instance so capacity can be
# checked across every AD first.
resource "oci_core_compute_capacity_report" "a1" {
  for_each = {
    for ad in data.oci_identity_availability_domains.all.availability_domains :
    ad.name => ad.name
  }

  availability_domain = each.value
  compartment_id      = var.tenancy_ocid

  shape_availabilities {
    instance_shape = var.shape

    instance_shape_config {
      ocpus         = var.ocpus
      memory_in_gbs = var.memory_in_gbs
    }
  }
}

output "a1_capacity" {
  description = "Current OCI host-capacity report for the requested A1 shape/config in every availability domain."
  value = {
    for ad_name, report in oci_core_compute_capacity_report.a1 :
    ad_name => [
      for availability in report.shape_availabilities : {
        availability_status = availability.availability_status
        available_count     = availability.available_count
        fault_domain        = availability.fault_domain
        ocpus               = availability.instance_shape_config[0].ocpus
        memory_in_gbs       = availability.instance_shape_config[0].memory_in_gbs
      }
    ]
  }
}
