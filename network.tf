resource "oci_core_vcn" "lab" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "${var.name_prefix}-vcn"
  dns_label      = "apexlab"
  freeform_tags  = local.tags
  depends_on     = [terraform_data.guardrails]
}

resource "oci_core_internet_gateway" "lab" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${var.name_prefix}-igw"
  enabled        = true
  freeform_tags  = local.tags
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${var.name_prefix}-routes"
  freeform_tags  = local.tags
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.lab.id
    description       = "Public VM: SSH, ADB public endpoint, software downloads and Codex"
  }
}

resource "oci_core_security_list" "dev" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.lab.id
  display_name   = "${var.name_prefix}-dev-security"
  freeform_tags  = local.tags

  ingress_security_rules {
    source      = local.rm_subnet_cidr
    source_type = "CIDR_BLOCK"
    protocol    = "6"
    stateless   = false
    description = "SSH from the dedicated Resource Manager private endpoint subnet"
    tcp_options {
      min = 22
      max = 22
    }
  }

  dynamic "ingress_security_rules" {
    for_each = toset(local.allowed_cidrs)
    content {
      source      = ingress_security_rules.value
      source_type = "CIDR_BLOCK"
      protocol    = "6"
      stateless   = false
      description = "SSH from an explicitly allowed client CIDR"
      tcp_options {
        min = 22
        max = 22
      }
    }
  }
  ingress_security_rules {
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    protocol    = "1"
    stateless   = false
    description = "Path MTU discovery only"
    icmp_options {
      type = 3
      code = 4
    }
  }

  dynamic "egress_security_rules" {
    for_each = toset([80, 443])
    content {
      destination      = "0.0.0.0/0"
      destination_type = "CIDR_BLOCK"
      protocol         = "6"
      stateless        = false
      description      = "Package repositories, HTTPS downloads, OCI APIs and Codex"
      tcp_options {
        min = egress_security_rules.value
        max = egress_security_rules.value
      }
    }
  }
  egress_security_rules {
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
    protocol         = "6"
    stateless        = false
    description      = "Outbound SQLcl mTLS to ADB public endpoint; ADB ACL restricts clients"
    tcp_options {
      min = 1522
      max = 1522
    }
  }
  dynamic "egress_security_rules" {
    for_each = { dns = 53, ntp = 123 }
    content {
      destination      = "169.254.169.254/32"
      destination_type = "CIDR_BLOCK"
      protocol         = "17"
      stateless        = false
      description      = "OCI link-local DNS / NTP"
      udp_options {
        min = egress_security_rules.value
        max = egress_security_rules.value
      }
    }
  }
  egress_security_rules {
    destination      = "169.254.169.254/32"
    destination_type = "CIDR_BLOCK"
    protocol         = "6"
    stateless        = false
    description      = "DNS TCP fallback"
    tcp_options {
      min = 53
      max = 53
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.lab.id
  cidr_block                 = local.subnet_cidr
  display_name               = "${var.name_prefix}-public"
  dns_label                  = "dev"
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.dev.id]
  prohibit_public_ip_on_vnic = false
  prohibit_internet_ingress  = false
  freeform_tags              = local.tags
}
