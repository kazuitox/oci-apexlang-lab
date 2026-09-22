terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "9.2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.7.2"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "4.1.0"
    }
  }
}

# Resource Manager supplies the authentication context; no API key is needed here.
provider "oci" {
  region = var.region
}

# IAM resources are managed in the tenancy home region even for a regional stack.
provider "oci" {
  alias  = "home"
  region = local.home_region
}
