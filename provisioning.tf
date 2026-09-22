resource "tls_private_key" "provisioner" {
  algorithm = "ED25519"
}

locals {
  rm_subnet_cidr = cidrsubnet(var.vcn_cidr, 8, 1)
  vm_config = {
    adb_ocid          = oci_database_autonomous_database.lab.id
    adb_name          = lower(local.effective_adb_name)
    region            = var.region
    auto_wallet       = var.create_wallet_iam
    initialize_apex   = var.initialize_apex
    apex_schema       = "APEXLAB"
    apex_workspace    = "APEXLAB"
    apex_user         = "APEXLAB"
    codex_version     = var.codex_version
    sqlcl_version     = "26.2.2.233.1901"
    sqlcl_url         = "https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-26.2.2.233.1901.zip"
    java_url          = "https://download.oracle.com/java/21/latest/jdk-21_linux-aarch64_bin.tar.gz"
    oracle_skills_url = "https://github.com/oracle/skills.git"
    # Verified main commit. Never depend on the upstream default branch or a moving HEAD.
    oracle_skills_revision = "b94ccf4dec34b27859c2378fa71ba2bad884f2fe"
  }
  provision_files = concat(
    ["playbooks/site.yml", "playbooks/tools.yml", "playbooks/apex.yml", "playbooks/apex-step.yml", "playbooks/callback_plugins/apexlang_retry.py"],
    ["vm/fetch-wallet.py", "vm/adb-connect", "vm/apexlang-status", "vm/requirements.txt",
    "vm/verify-adb-network.py", "vm/bootstrap-apex.py", "scripts/run-ansible.sh", "sql/verify-apex.sql", "apex-study/AGENTS.md"],
    [for name in fileset(path.module, "sql/bootstrap-*.sql") : name]
  )
}

# Only the dedicated endpoint subnet can originate deployment SSH connections.
resource "oci_core_route_table" "rm" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${var.name_prefix}-rm-local-routes"
  freeform_tags  = local.tags
}

resource "oci_core_security_list" "rm" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${var.name_prefix}-rm-security"
  freeform_tags  = local.tags
  egress_security_rules {
    destination      = "${oci_core_instance.dev.private_ip}/32"
    destination_type = "CIDR_BLOCK"
    protocol         = "6"
    stateless        = false
    tcp_options {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_subnet" "rm" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.lab.id
  cidr_block                 = local.rm_subnet_cidr
  display_name               = "${var.name_prefix}-rm-private"
  route_table_id             = oci_core_route_table.rm.id
  security_list_ids          = [oci_core_security_list.rm.id]
  prohibit_public_ip_on_vnic = true
  prohibit_internet_ingress  = true
  freeform_tags              = local.tags
}

resource "oci_resourcemanager_private_endpoint" "provisioner" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  subnet_id      = oci_core_subnet.rm.id
  display_name   = "${var.name_prefix}-rm-endpoint"
  description    = "Ansible deployment access to the APEXlang VM"
  freeform_tags  = local.tags
}

data "oci_resourcemanager_private_endpoint_reachable_ip" "vm" {
  private_endpoint_id = oci_resourcemanager_private_endpoint.provisioner.id
  private_ip          = oci_core_instance.dev.private_ip
}

# A failed provisioner taints this terraform_data resource, never the VM.
resource "terraform_data" "configure" {
  depends_on = [oci_identity_policy.wallet]
  triggers_replace = {
    instance    = oci_core_instance.dev.id
    config      = sha256(jsonencode(local.vm_config))
    files       = sha256(join("", [for name in local.provision_files : filesha256("${path.module}/${name}")]))
    revision    = var.provision_revision
    credentials = var.initialize_apex ? sha256(var.adb_admin_password) : "disabled"
  }
  connection {
    type        = "ssh"
    host        = data.oci_resourcemanager_private_endpoint_reachable_ip.vm.ip_address
    user        = "opc"
    agent       = false
    private_key = tls_private_key.provisioner.private_key_openssh
    timeout     = "15m"
  }
  provisioner "remote-exec" {
    inline = ["umask 077; mkdir -p /home/opc/apexlang-provision/apex-study; chmod 700 /home/opc/apexlang-provision"]
  }
  provisioner "file" {
    source      = "${path.module}/playbooks"
    destination = "/home/opc/apexlang-provision/"
  }
  provisioner "file" {
    source      = "${path.module}/vm"
    destination = "/home/opc/apexlang-provision/"
  }
  provisioner "file" {
    source      = "${path.module}/sql"
    destination = "/home/opc/apexlang-provision/"
  }
  # Transfer only the instructions, never applications or credentials in the workspace.
  provisioner "file" {
    source      = "${path.module}/apex-study/AGENTS.md"
    destination = "/home/opc/apexlang-provision/apex-study/AGENTS.md"
  }
  provisioner "file" {
    source      = "${path.module}/scripts/run-ansible.sh"
    destination = "/home/opc/apexlang-provision/run-ansible.sh"
  }
  provisioner "file" {
    content     = jsonencode(local.vm_config)
    destination = "/home/opc/apexlang-provision/config.json"
  }
  provisioner "remote-exec" {
    inline = ["umask 077; install -m 600 /dev/null /home/opc/apexlang-provision/bootstrap-secrets.json"]
  }
  # Sensitive content is uploaded separately; remote-exec contains no secret so TASK logs stay visible.
  provisioner "file" {
    content     = var.initialize_apex ? jsonencode({ password = var.adb_admin_password }) : "{}"
    destination = "/home/opc/apexlang-provision/bootstrap-secrets.json"
  }
  provisioner "remote-exec" {
    inline = ["sudo bash /home/opc/apexlang-provision/run-ansible.sh"]
  }
}
