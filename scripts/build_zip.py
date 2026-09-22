#!/usr/bin/env python3
"""Build a Resource Manager archive from an explicit allowlist, never the whole workspace."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "versions.tf", "variables.tf", "data.tf", "naming.tf", "network.tf", "database.tf",
    "compute.tf", "iam.tf", "provisioning.tf", "outputs.tf", "schema.yaml", ".terraform.lock.hcl",
    "README.md", "terraform.tfvars.example", "apex-study/AGENTS.md",
    "vm/fetch-wallet.py", "vm/adb-connect", "vm/apexlang-status", "vm/requirements.txt",
    "vm/verify-adb-network.py", "vm/bootstrap-apex.py", "playbooks/site.yml", "playbooks/tools.yml",
    "playbooks/apex.yml", "playbooks/apex-step.yml",
    "playbooks/callback_plugins/apexlang_retry.py",
    "scripts/run-ansible.sh", "sql/verify-apex.sql",
    "sql/bootstrap-preflight.sql", "sql/bootstrap-schema.sql", "sql/bootstrap-workspace.sql",
    "sql/bootstrap-account.sql", "sql/bootstrap-verify.sql",
    "scripts/build_zip.py", "tests/README.md", "tests/requirements.txt",
    "tests/test_stack.py", "tests/test_apex_bootstrap.py", "tests/test_oracle_skills.py", "tests/validate_rm_schema.py",
]


def build(destination):
    for name in FILES:
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing regular source file: {name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            # Fixed timestamps keep an unchanged source tree reproducible.
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (ROOT / name).read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


if __name__ == "__main__":
    output = ROOT / "dist/apexlang-oci-resource-manager.zip"
    digest = build(output)
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n")
    print(f"{output}\nSHA256 {digest}")
