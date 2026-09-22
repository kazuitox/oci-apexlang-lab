# cloud-init only establishes OS access. Tool installation is synchronous Ansible.
locals {
  cloud_init = "#cloud-config\n${yamlencode({
    ssh_pwauth   = false
    disable_root = true
  })}"
}

resource "oci_core_instance" "dev" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "${var.name_prefix}-dev"
  shape               = "VM.Standard.A1.Flex"
  freeform_tags       = local.tags

  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
    hostname_label   = "apexdev"
    display_name     = "${var.name_prefix}-dev-vnic"
  }
  source_details {
    source_type             = "image"
    source_id               = var.image_ocid
    boot_volume_size_in_gbs = 50
    boot_volume_vpus_per_gb = 10
  }
  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }
  metadata = {
    ssh_authorized_keys = "${trimspace(var.ssh_public_key)}\n${trimspace(tls_private_key.provisioner.public_key_openssh)}"
    user_data           = base64encode(local.cloud_init)
  }
  preserve_boot_volume = false

  lifecycle {
    precondition {
      condition     = length(base64encode(local.cloud_init)) + length(var.ssh_public_key) + length(tls_private_key.provisioner.public_key_openssh) + 1 < 32000
      error_message = "cloud-initとSSH鍵がOCI metadataのサイズ上限に近づいています。"
    }
  }
  timeouts {
    create = "30m"
  }
}
