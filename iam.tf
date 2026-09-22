resource "oci_identity_dynamic_group" "wallet" {
  provider       = oci.home
  count          = var.create_wallet_iam ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = "${var.name_prefix}-wallet-vm"
  description    = "Only the APEXlang development VM may request its database wallet"
  matching_rule  = "ALL {instance.id = '${oci_core_instance.dev.id}'}"
  freeform_tags  = local.tags
}

resource "oci_identity_policy" "wallet" {
  provider       = oci.home
  count          = var.create_wallet_iam ? 1 : 0
  compartment_id = var.compartment_ocid
  name           = "${var.name_prefix}-wallet-download"
  description    = "Download only this database wallet from the development VM"
  # ADB Serverless documents target.id (not Dedicated's target.database.id).
  statements = [
    "Allow dynamic-group id ${oci_identity_dynamic_group.wallet[0].id} to read autonomous-databases in compartment id ${var.compartment_ocid} where all {target.id = '${oci_database_autonomous_database.lab.id}', request.operation = 'GenerateAutonomousDatabaseWallet'}"
  ]
  freeform_tags = local.tags
}
