# Generate once per Terraform state. No timestamp/uuid() or changing keepers:
# normal Plan/Apply and unrelated edits must keep the same database name.
resource "random_id" "adb_suffix" {
  byte_length = 4
}

locals {
  # Keep the 14-character limit used by this stack, including Always Free.
  # name_prefix begins with a letter; remove hyphens and retain up to 6 chars.
  generated_adb_name = upper("${substr(replace(var.name_prefix, "-", ""), 0, 6)}${random_id.adb_suffix.hex}")
  effective_adb_name = var.generate_adb_name ? local.generated_adb_name : upper(var.adb_name)
  # Display names allow hyphens; keep db_name unchanged to preserve deployed DBs.
  adb_display_name = var.generate_adb_name ? upper("${var.name_prefix}-${random_id.adb_suffix.hex}") : upper("${var.name_prefix}-${var.adb_name}")
}
