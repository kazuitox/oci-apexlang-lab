locals {
  # An IGW connection is seen by the ADB as the VM's public source address.
  adb_allowed_cidrs = distinct(concat(local.allowed_cidrs, ["${oci_core_instance.dev.public_ip}/32"]))
}

resource "oci_database_autonomous_database" "lab" {
  compartment_id                      = var.compartment_ocid
  display_name                        = local.adb_display_name
  db_name                             = local.effective_adb_name
  db_version                          = var.adb_version
  db_workload                         = "OLTP"
  admin_password                      = var.adb_admin_password
  is_free_tier                        = var.use_always_free
  is_dedicated                        = false
  compute_model                       = local.adb_capacity.compute_model
  cpu_core_count                      = local.adb_capacity.cpu_core_count
  compute_count                       = local.adb_capacity.compute_count
  data_storage_size_in_gb             = local.adb_capacity.data_storage_size_in_gb
  license_model                       = "LICENSE_INCLUDED"
  is_auto_scaling_enabled             = false
  is_auto_scaling_for_storage_enabled = false
  is_mtls_connection_required         = true
  # Public endpoint: allow explicitly listed external clients and this VM only.
  whitelisted_ips = local.adb_allowed_cidrs
  freeform_tags   = local.tags

  timeouts {
    create = "60m"
    update = "60m"
    delete = "60m"
  }
}
