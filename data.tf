data "oci_identity_region_subscriptions" "tenancy" {
  tenancy_id = var.tenancy_ocid
}

# Lookup a user-selected, fixed image, not a rolling latest-image list.
data "oci_core_image" "selected" {
  image_id = var.image_ocid
}

locals {
  home_region = one([
    for subscription in data.oci_identity_region_subscriptions.tenancy.region_subscriptions :
    subscription.region_name if subscription.is_home_region
  ])
  adb_capacity = {
    compute_model           = var.use_always_free ? "OCPU" : "ECPU"
    cpu_core_count          = var.use_always_free ? 1 : null
    compute_count           = var.use_always_free ? null : 2
    data_storage_size_in_gb = 20
  }
  allowed_cidrs = distinct([for entry in split(",", var.allowed_client_cidrs) : trimspace(entry)])
  subnet_cidr   = cidrsubnet(var.vcn_cidr, 8, 0)
  tags          = { project = "APEXlang", stack = var.name_prefix }
}

resource "terraform_data" "guardrails" {
  lifecycle {
    precondition {
      condition     = !var.initialize_apex || var.create_wallet_iam
      error_message = "APEX自動初期化にはWallet自動取得が必要です。手動Wallet構成ではinitialize_apexもfalseにしてください。"
    }
    precondition {
      condition     = !var.use_always_free || var.region == local.home_region
      error_message = "Always Free構成はホームリージョンでデプロイしてください。有料で別リージョンを使う場合は use_always_free = false を指定してください。"
    }
    precondition {
      condition = (
        data.oci_core_image.selected.operating_system == "Oracle Linux" &&
        startswith(data.oci_core_image.selected.operating_system_version, "8") &&
        can(regex("(?i)aarch64", data.oci_core_image.selected.display_name))
      )
      error_message = "Oracle Linux 8のaarch64プラットフォームイメージを選択してください。"
    }
  }
}
