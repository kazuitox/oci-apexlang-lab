"""Local checks without OCI calls. State persistence also uses the cached Random provider."""
import importlib.util
import gzip
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile
import zlib

import hcl2
import yaml
from oci._vendor.requests import Response as SDKHTTPResponse
from urllib3.response import HTTPResponse

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = os.environ.get("TERRAFORM", "terraform")


def load_module(name, source):
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wallet = load_module("wallet", ROOT / "vm/fetch-wallet.py")
packager = load_module("packager", ROOT / "scripts/build_zip.py")


def archive_payload(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("tnsnames.ora", "test_low = (description=example)")
        archive.writestr("cwallet.sso", b"fake-test-wallet")
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def wallet_http_response(payload, encoding="identity"):
    response = SDKHTTPResponse()
    response.status_code = 200
    response.headers["Content-Type"] = "application/octet-stream"
    response.headers["Content-Encoding"] = encoding
    encoded = {"identity": lambda value: value, "gzip": gzip.compress, "deflate": zlib.compress}[encoding](payload)
    response.raw = HTTPResponse(body=io.BytesIO(encoded), headers=response.headers, status=200,
                                preload_content=False, decode_content=False)
    return response


class WalletTests(unittest.TestCase):
    def test_download_accepts_encoded_and_buffered_sdk_http_responses(self):
        payload = archive_payload()
        for encoding in ("identity", "gzip", "deflate"):
            for buffered in (False, True):
                with self.subTest(encoding=encoding, buffered=buffered):
                    response = wallet_http_response(payload, encoding)
                    if buffered:
                        self.assertEqual(response.content, payload)
                    sdk = mock.Mock()
                    sdk.database.DatabaseClient.return_value.generate_autonomous_database_wallet.return_value.data = response
                    with mock.patch.dict(sys.modules, {"oci": sdk}), mock.patch.object(response, "close", wraps=response.close) as close:
                        result = wallet.download_wallet({"adb_ocid": "test-only", "region": "ap-osaka-1"})
                    self.assertEqual(result, payload)
                    close.assert_called_once_with()
                    wallet.validate_wallet(result)

    def test_download_rejects_oversized_decoded_body_and_closes_response(self):
        response = wallet_http_response(b"x" * 8192, "gzip")
        sdk = mock.Mock()
        sdk.database.DatabaseClient.return_value.generate_autonomous_database_wallet.return_value.data = response
        with mock.patch.dict(sys.modules, {"oci": sdk}), mock.patch.object(wallet, "MAX_WALLET_BYTES", 4096), \
                mock.patch.object(response, "close", wraps=response.close) as close:
            with self.assertRaises(wallet.WalletFailure) as caught:
                wallet.download_wallet({"adb_ocid": "test-only", "region": "ap-osaka-1"})
        self.assertEqual(caught.exception.stage, "download_wallet")
        self.assertIsInstance(caught.exception.cause, ValueError)
        close.assert_called_once_with()

    def test_invalid_wallet_is_reported_as_permanent_validation_failure(self):
        for payload in (b"not a ZIP", archive_payload({"../escape": "bad"})):
            with self.subTest(payload_size=len(payload)):
                sdk = mock.Mock()
                sdk.database.DatabaseClient.return_value.generate_autonomous_database_wallet.return_value.data = wallet_http_response(payload)
                with mock.patch.dict(sys.modules, {"oci": sdk}), self.assertRaises(wallet.WalletFailure) as caught:
                    wallet.download_wallet({"adb_ocid": "test-only", "region": "ap-osaka-1"})
                self.assertEqual(caught.exception.stage, "validate_wallet")
                self.assertEqual(wallet.failure_exit_code(caught.exception), 2)
                self.assertEqual(wallet.failure_summary(caught.exception)["stage"], "validate_wallet")

    def test_failure_diagnostics_identify_stage_without_exception_body(self):
        config = {"adb_ocid": "ocid1.autonomousdatabase.example", "region": "ap-osaka-1"}
        for stage in ("instance_principal", "generate_wallet", "download_wallet"):
            with self.subTest(stage=stage):
                sdk = mock.Mock()
                error = type("ServiceError", (Exception,), {})("SECRET request body and wallet password")
                error.status = 404
                error.code = "NotAuthorizedOrNotFound"
                operations = {
                    "instance_principal": sdk.auth.signers.InstancePrincipalsSecurityTokenSigner,
                    "generate_wallet": sdk.database.DatabaseClient.return_value.generate_autonomous_database_wallet,
                    "download_wallet": sdk.database.DatabaseClient.return_value.generate_autonomous_database_wallet.return_value.data.iter_content,
                }
                operations[stage].side_effect = error
                with mock.patch.dict(sys.modules, {"oci": sdk}), self.assertRaises(wallet.WalletFailure) as caught:
                    wallet.download_wallet(config)
                summary = wallet.failure_summary(caught.exception)
                self.assertEqual(summary, {"stage": stage, "error": "ServiceError", "http_status": 404,
                                           "code": "NotAuthorizedOrNotFound"})
                self.assertNotIn("SECRET", json.dumps(summary))
                self.assertEqual(wallet.failure_exit_code(caught.exception), 1)

    def test_download_uses_configured_database_id(self):
        config = {"adb_ocid": "ocid1.autonomousdatabase.example", "region": "ap-osaka-1"}
        sdk = mock.Mock()
        client = sdk.database.DatabaseClient.return_value
        response = client.generate_autonomous_database_wallet.return_value
        payload = archive_payload()
        response.data.iter_content.return_value = [payload[:20], payload[20:]]
        with mock.patch.dict(sys.modules, {"oci": sdk}):
            self.assertEqual(wallet.download_wallet(config), payload)
        sdk.database.DatabaseClient.assert_called_once_with(
            {"region": config["region"]}, signer=sdk.auth.signers.InstancePrincipalsSecurityTokenSigner.return_value,
            timeout=(15, 90))
        client.generate_autonomous_database_wallet.assert_called_once_with(
            config["adb_ocid"], sdk.database.models.GenerateAutonomousDatabaseWalletDetails.return_value)
        client.list_autonomous_databases.assert_not_called()
        response.data.close.assert_called_once_with()

    def test_download_requires_database_id_before_calling_oci(self):
        for config in ({"region": "ap-osaka-1"}, {"region": "ap-osaka-1", "adb_ocid": ""}):
            with self.subTest(config=config):
                sdk = mock.Mock()
                with mock.patch.dict(sys.modules, {"oci": sdk}), self.assertRaises((KeyError, ValueError)):
                    wallet.download_wallet(config)
                self.assertEqual(sdk.mock_calls, [])

    def test_accepts_expected_wallet_files(self):
        wallet.validate_wallet(archive_payload())

    def test_rejects_non_zip(self):
        with self.assertRaises(zipfile.BadZipFile):
            wallet.validate_wallet(b"not a zip")

    def test_rejects_missing_credentials(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("README", "no credentials")
        with self.assertRaises(ValueError):
            wallet.validate_wallet(output.getvalue())

    def test_rejects_traversal_and_absolute_paths(self):
        for name in ("../escape", "/absolute", "nested/../../escape"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                wallet.validate_wallet(archive_payload({name: "bad"}))

    def test_rejects_expansion_beyond_limit(self):
        with mock.patch.object(wallet, "MAX_WALLET_BYTES", 4096):
            with self.assertRaises(ValueError):
                wallet.validate_wallet(archive_payload({"large.txt": "x" * 8192}))

    def test_invalid_refresh_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "wallet.zip"
            target.write_bytes(b"existing wallet")
            with self.assertRaises(zipfile.BadZipFile):
                wallet.save_wallet(b"invalid response", target, os.getuid(), os.getgid())
            self.assertEqual(target.read_bytes(), b"existing wallet")

    def test_successful_save_has_restricted_permissions_and_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / ".adb/wallet.zip"
            payload = archive_payload()
            with mock.patch.object(wallet.os, "chown"), mock.patch.object(wallet.os, "fchown"):
                wallet.save_wallet(payload, target, os.getuid(), os.getgid())
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_failed_replace_preserves_existing_wallet_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / ".adb/wallet.zip"
            target.parent.mkdir()
            target.write_bytes(b"existing wallet")
            with mock.patch.object(wallet.os, "chown"), mock.patch.object(wallet.os, "fchown"), \
                    mock.patch.object(wallet.os, "replace", side_effect=OSError("test failure")):
                with self.assertRaises(OSError):
                    wallet.save_wallet(archive_payload(), target, os.getuid(), os.getgid())
            self.assertEqual(target.read_bytes(), b"existing wallet")
            self.assertEqual(list(target.parent.iterdir()), [target])


class PackageTests(unittest.TestCase):
    def test_allowlist_excludes_state_credentials_and_unexpected_files(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / "source"
            fixture.mkdir()
            canary = secrets.token_hex(32)
            for name in packager.FILES:
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            for name in ("terraform.tfstate", "terraform.tfvars", "private.key", "Wallet.zip", ".terraform/secret", ".git/config",
                         "apex-study/private-app/application.apx", "apex-study/private-app/.env"):
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(canary)
            output = Path(folder) / "stack.zip"
            with mock.patch.object(packager, "ROOT", fixture):
                first = packager.build(output)
                self.assertEqual(first, packager.build(output))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(packager.FILES))
                self.assertIn("versions.tf", archive.namelist())
                self.assertIn("schema.yaml", archive.namelist())
                for name in archive.namelist():
                    self.assertNotIn(canary.encode(), archive.read(name))


class TerraformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.temp.name)
        shutil.copyfile(ROOT / "variables.tf", cls.fixture / "variables.tf")
        for name in ("vm", "sql", "playbooks", "scripts"):
            shutil.copytree(ROOT / name, cls.fixture / name)
        (cls.fixture / "apex-study").mkdir()
        shutil.copyfile(ROOT / "apex-study/AGENTS.md", cls.fixture / "apex-study/AGENTS.md")
        # Render the real VM locals without an ADB stub: VM creation must not wait for the ADB.
        source = (ROOT / "compute.tf").read_text().split('\nresource "oci_core_instance"')[0]
        (cls.fixture / "render.tf").write_text(source)
        naming = "locals {" + (ROOT / "naming.tf").read_text().split("locals {", 1)[1]
        (cls.fixture / "naming.tf").write_text(naming.replace("random_id.adb_suffix.hex", '"1a2b3c4d"'))
        provision_source = (ROOT / "provisioning.tf").read_text().split("locals {", 1)[1].split("\n# Only the dedicated", 1)[0]
        provision_source = "locals {" + provision_source
        provision_source = provision_source.replace("oci_database_autonomous_database.lab.id", '"ocid1.autonomousdatabase.example"')
        (cls.fixture / "provision-locals.tf").write_text(provision_source)
        acl_source = (ROOT / "database.tf").read_text().split('\nresource "oci_database_autonomous_database"')[0]
        acl_source = acl_source.replace("oci_core_instance.dev.public_ip", '"192.0.2.50"')
        (cls.fixture / "acl.tf").write_text(acl_source)
        # Keep the real region guard and capacity expressions; substitute only OCI API responses.
        data_source = "locals {" + (ROOT / "data.tf").read_text().split("locals {", 1)[1]
        data_source = data_source.replace("data.oci_identity_region_subscriptions.tenancy.region_subscriptions", "local.fixture_subscriptions")
        data_source = data_source.replace("data.oci_core_image.selected", "local.fixture_image")
        (cls.fixture / "guardrails.tf").write_text(data_source)
        (cls.fixture / "api-responses.tf").write_text('''
locals {
  fixture_subscriptions = [
    { region_name = "ap-osaka-1", is_home_region = false },
    { region_name = "ap-tokyo-1", is_home_region = true }
  ]
  fixture_image = { operating_system = "Oracle Linux", operating_system_version = "8", display_name = "Oracle-Linux-8.10-aarch64" }
}
''')
        (cls.fixture / "probe.tf").write_text('resource "terraform_data" "probe" { input = var.allowed_client_cidrs }\n')
        cls.values = {
            "tenancy_ocid": "ocid1.tenancy.example", "compartment_ocid": "ocid1.compartment.example",
            "region": "ap-tokyo-1", "availability_domain": "example:AP-TOKYO-1-AD-1",
            "image_ocid": "ocid1.image.example", "ssh_public_key": "ssh-ed25519 " + "A" * 68,
            "allowed_client_cidrs": "203.0.113.10/32, 198.51.100.0/24",
            "adb_admin_password": "OnlyTestPassword72!", "create_wallet_iam": True,
        }
        (cls.fixture / "fixture.auto.tfvars.json").write_text(json.dumps(cls.values))
        cls.run_tf("init", "-backend=false", "-input=false")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def run_tf(cls, *args, text_input=None, check=True):
        result = subprocess.run([TERRAFORM, *args, "-no-color"], cwd=cls.fixture,
                                input=text_input, text=True, capture_output=True)
        if check and result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def test_terraform_accepts_valid_inputs(self):
        self.run_tf("plan", "-input=false", "-lock=false")

    def test_adb_acl_allows_external_clients_and_only_the_vm_public_host(self):
        result = self.run_tf("console", text_input="jsonencode(local.adb_allowed_cidrs)\n")
        cidrs = json.loads(json.loads(result.stdout))
        self.assertCountEqual(cidrs, ["203.0.113.10/32", "198.51.100.0/24", "192.0.2.50/32"])

    def test_automatic_name_ignores_fixed_name(self):
        result = self.run_tf("console", "-var=adb_name=APEXLANG", text_input="local.effective_adb_name\n")
        self.assertEqual(json.loads(result.stdout), "APEXLA1A2B3C4D")

    def test_generated_names_handle_hyphens_and_prefix_length(self):
        for prefix, expected in (("a--", "A1A2B3C4D"), ("lab-dev", "LABDEV1A2B3C4D"),
                                 ("abcdefghijklmnopqrst", "ABCDEF1A2B3C4D")):
            with self.subTest(prefix=prefix):
                result = self.run_tf("console", f"-var=name_prefix={prefix}", text_input="local.effective_adb_name\n")
                name = json.loads(result.stdout)
                self.assertEqual(name, expected)
                self.assertRegex(name, r"^[A-Z][A-Z0-9]{0,13}$")

    def test_fixed_name_mode_uses_requested_database_name(self):
        result = self.run_tf("console", "-var=generate_adb_name=false", "-var=adb_name=StudyDb1",
                             text_input="local.effective_adb_name\n")
        self.assertEqual(json.loads(result.stdout), "STUDYDB1")

    def test_invalid_prefix_and_fixed_name_are_rejected(self):
        for variable, value in (("name_prefix", "-bad"), ("name_prefix", "0bad"), ("name_prefix", "bad_name"),
                                ("adb_name", "BAD-NAME"), ("adb_name", "0BAD"), ("adb_name", "A" * 15)):
            with self.subTest(variable=variable, value=value):
                result = self.run_tf("plan", "-input=false", "-lock=false", f"-var={variable}={value}", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid value for variable", result.stderr)

    def test_display_name_has_hyphen_without_changing_database_identifier(self):
        result = self.run_tf("console", text_input="jsonencode([local.adb_display_name, local.effective_adb_name])\n")
        self.assertEqual(json.loads(json.loads(result.stdout)), ["APEXLANG-1A2B3C4D", "APEXLA1A2B3C4D"])

    def test_ansible_config_contains_exact_database_id_and_no_credentials(self):
        result = self.run_tf("console", text_input="jsonencode(local.vm_config)\n")
        config = json.loads(json.loads(result.stdout))
        self.assertEqual(config["adb_ocid"], "ocid1.autonomousdatabase.example")
        self.assertEqual(config["adb_name"], "apexla1a2b3c4d")
        self.assertNotIn("private_key", json.dumps(config))
        self.assertNotIn(self.values["adb_admin_password"], json.dumps(config))

    def test_paid_mode_accepts_non_home_region_and_resolves_home_for_iam(self):
        self.run_tf("plan", "-input=false", "-lock=false", "-var=region=ap-osaka-1", "-var=use_always_free=false")
        result = self.run_tf("console", "-var=region=ap-osaka-1", text_input="local.home_region\n")
        self.assertEqual(json.loads(result.stdout), "ap-tokyo-1")

    def test_always_free_accepts_home_region(self):
        self.run_tf("plan", "-input=false", "-lock=false", "-var=region=ap-tokyo-1", "-var=use_always_free=true")

    def test_always_free_rejects_non_home_region_with_recovery_message(self):
        result = self.run_tf("plan", "-input=false", "-lock=false", "-var=region=ap-osaka-1", "-var=use_always_free=true", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Resource precondition failed", result.stderr)
        self.assertIn("use_always_free = false", result.stderr)

    def test_paid_and_free_capacity_do_not_mix_cpu_models(self):
        for free in (False, True):
            with self.subTest(free=free):
                result = self.run_tf("console", f"-var=use_always_free={str(free).lower()}", text_input="jsonencode(local.adb_capacity)\n")
                capacity = json.loads(json.loads(result.stdout))
                self.assertEqual(capacity["data_storage_size_in_gb"], 20)
                self.assertEqual(capacity["compute_model"], "OCPU" if free else "ECPU")
                self.assertEqual(capacity["cpu_core_count"], 1 if free else None)
                self.assertEqual(capacity["compute_count"], None if free else 2)

    def test_terraform_rejects_invalid_or_world_open_cidrs(self):
        for cidr in ("0.0.0.0/0", "", "::/0", "203.0.113.300/32", "203.0.113.1", "203.0.113.10/32,", "203.0.113.10/32,0.0.0.0/0"):
            with self.subTest(cidr=cidr):
                result = self.run_tf("plan", "-input=false", "-lock=false", f"-var=allowed_client_cidrs={cidr}", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid value for variable", result.stderr)

    def test_terraform_rejects_invalid_admin_passwords(self):
        for password in ("short1A", "lowercaseonly72", "OnlyUPPER72ADMIN", "WithQuote72A\"", "WithNewline72A\n", "APEXLABpass72!", "WithTab72A\txx"):
            with self.subTest(password_kind="invalid"):
                result = self.run_tf("plan", "-input=false", "-lock=false", f"-var=adb_admin_password={password}", check=False)
                self.assertNotEqual(result.returncode, 0)

    def render_cloud_init(self, auto_wallet):
        result = self.run_tf("console", f"-var=create_wallet_iam={str(auto_wallet).lower()}", text_input="jsonencode(local.cloud_init)\n")
        return json.loads(json.loads(result.stdout))

    def test_cloud_init_only_sets_os_access_and_never_installs_tools(self):
        rendered = self.render_cloud_init(True)
        document = yaml.safe_load(rendered)
        self.assertEqual(document, {"ssh_pwauth": False, "disable_root": True})
        self.assertNotIn(self.values["adb_admin_password"], rendered)
        self.assertNotIn("runcmd", document)
        self.assertNotIn("write_files", document)

    def test_manual_wallet_setting_is_passed_to_ansible(self):
        result = self.run_tf("console", "-var=create_wallet_iam=false", text_input="jsonencode(local.vm_config)\n")
        self.assertFalse(json.loads(json.loads(result.stdout))["auto_wallet"])

    def test_apex_initialization_requires_automatic_wallet(self):
        rejected = self.run_tf("plan", "-input=false", "-lock=false", "-var=create_wallet_iam=false", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("initialize_apex", rejected.stdout + rejected.stderr)
        self.run_tf("plan", "-input=false", "-lock=false", "-var=create_wallet_iam=false", "-var=initialize_apex=false")


class RandomStateTests(unittest.TestCase):
    def test_random_name_survives_reapply_and_differs_between_independent_states(self):
        # Only local random_id resources are applied here. No OCI provider/configuration.
        def run(folder, *args):
            result = subprocess.run([TERRAFORM, *args, "-no-color"], cwd=folder, text=True, capture_output=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            return result

        with tempfile.TemporaryDirectory() as temp:
            names = []
            for number in range(2):
                folder = Path(temp) / str(number)
                folder.mkdir()
                shutil.copyfile(ROOT / "naming.tf", folder / "naming.tf")
                shutil.copyfile(ROOT / ".terraform.lock.hcl", folder / ".terraform.lock.hcl")
                with (ROOT / "versions.tf").open() as stream:
                    version = hcl2.load(stream)["terraform"][0]["required_providers"][0]["random"]["version"]
                    version = version.strip('"')
                (folder / "main.tf").write_text('''
terraform {
  required_providers {
    random = { source = "hashicorp/random", version = "''' + version + '''" }
  }
}
variable "name_prefix" { default = "apexlang" }
variable "generate_adb_name" { default = true }
variable "adb_name" { default = "APEXLANG" }
variable "unrelated_value" { default = "before" }
output "name" { value = local.effective_adb_name }
''')
                # init verifies the copied hashes and removes the unused OCI lock entry.
                run(folder, "init", "-backend=false", "-input=false",
                    f"-plugin-dir={ROOT / '.terraform/providers'}")
                run(folder, "apply", "-auto-approve", "-input=false")
                first = json.loads(run(folder, "output", "-json").stdout)["name"]["value"]
                run(folder, "apply", "-auto-approve", "-input=false", "-var=unrelated_value=after")
                second = json.loads(run(folder, "output", "-json").stdout)["name"]["value"]
                self.assertEqual(first, second)
                self.assertRegex(first, r"^APEXLA[A-F0-9]{8}$")
                run(folder, "plan", "-detailed-exitcode", "-input=false")
                names.append(first)
            self.assertNotEqual(names[0], names[1])


class SqlclTests(unittest.TestCase):
    def run_play(self, work, tasks, variables=None):
        playfile = work / "sqlcl.yml"
        playfile.write_text(yaml.safe_dump([{"hosts": "all", "gather_facts": False,
                                             "vars": variables or {}, "tasks": tasks}]))
        return subprocess.run(
            [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", "-c", "local",
             "-e", f"ansible_python_interpreter={sys.executable}", str(playfile)],
            env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(work / "ansible-temp"),
                 "ANSIBLE_REMOTE_TEMP": str(work / "ansible-remote-temp"),
                 "ANSIBLE_NOCOLOR": "1", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
            text=True, capture_output=True)

    def test_distribution_permissions_allow_library_reads_without_exposing_wallet(self):
        tools = yaml.safe_load((ROOT / "playbooks/tools.yml").read_text())
        task = next(item for item in tools if item["name"] == "Make SQLcl distribution readable by development users")
        # Exercise the real permission task as the local test user, without root ownership changes.
        task["ansible.builtin.file"].pop("owner")
        task["ansible.builtin.file"].pop("group")
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            app = work / "app"
            library = app / "sqlcl/lib/dbtools-sqlcl.jar"
            executable = app / "sqlcl/bin/sql"
            secret = app / "wallet.zip"
            for target, mode in ((library, 0o640), (executable, 0o755), (secret, 0o600)):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("test fixture")
                target.chmod(mode)
            for iteration in range(2):
                result = self.run_play(work, [task], {"app_dir": str(app)})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(stat.S_IMODE(library.stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE(executable.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE(library.parent.stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
                if iteration:
                    self.assertIn("changed=0", result.stdout)

    def test_startup_failure_prevents_tools_ready_even_with_zero_exit_code(self):
        original = yaml.safe_load((ROOT / "playbooks/site.yml").read_text())[0]["tasks"]
        tasks = {task["name"]: task for task in original}
        startup = tasks["Verify SQLcl starts and executes commands as opc"]
        ready = tasks["Mark verified tools ready"]
        self.assertTrue(startup["become"])
        self.assertEqual(startup["become_user"], "opc")
        self.assertLess(original.index(startup), original.index(ready))
        self.assertEqual(startup["ansible.builtin.command"]["argv"],
                         ["/usr/bin/timeout", "60s", "/usr/local/bin/sql", "-s", "-L", "/nolog"])
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            helper = work / "sqlcl-fixture.py"
            helper.write_text('''import os, sys
commands = sys.stdin.read().strip().splitlines()
assert commands == ['prompt APEXLANG_SQLCL_READY', 'exit']
scenario = os.environ['SQLCL_TEST_SCENARIO']
if scenario != 'missing-marker':
    print('APEXLANG_SQLCL_READY')
sys.exit(1 if scenario == 'failed-startup' else 0)
''')
            startup["become"] = False
            startup["ansible.builtin.command"]["argv"] = [sys.executable, str(helper)]
            for scenario in ("success", "missing-marker", "failed-startup"):
                with self.subTest(scenario=scenario):
                    marker = work / "tools.ready"
                    marker.write_text("previous run")
                    startup["environment"]["SQLCL_TEST_SCENARIO"] = scenario
                    result = self.run_play(work, [tasks["Mark tool verification as pending for this run"],
                                                  startup, ready],
                                           {"dev_home": str(work), "state_dir": str(work)})
                    self.assertEqual(result.returncode, 0 if scenario == "success" else 2,
                                     result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stdout + result.stderr)
                    self.assertEqual(marker.exists(), scenario == "success")


class ProvisioningTests(unittest.TestCase):
    def test_invalid_wallet_fails_ansible_without_repeating_the_download(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            helper = work / "invalid-wallet.py"
            helper.write_text('''import sys
from pathlib import Path
counter = Path(__file__).with_suffix('.count')
counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))
print('APEXLANG_WALLET_ERROR {"stage":"validate_wallet","error":"BadZipFile"}', file=sys.stderr)
sys.exit(2)
''')
            original = yaml.safe_load((ROOT / "playbooks/site.yml").read_text())[0]
            task = next(item for item in original["tasks"] if "apexlang_wallet" in item.get("tags", []))
            task["ansible.builtin.command"]["argv"] = [sys.executable, str(helper)]
            task.update(retries=2, delay=0)
            playfile = work / "invalid.yml"
            playfile.write_text(yaml.safe_dump([{"hosts": "all", "gather_facts": False, "vars": {
                "auto_wallet": True, "config_copy": {"changed": True},
                "wallet_marker": {"stat": {"exists": False}},
            }, "tasks": [task]}]))
            result = subprocess.run(
                [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", "-c", "local",
                 "-e", f"ansible_python_interpreter={sys.executable}", str(playfile)],
                env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(work / "ansible-temp"),
                     "ANSIBLE_NOCOLOR": "1", "ANSIBLE_VERBOSITY": "0", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(helper.with_suffix(".count").read_text(), "1")
            self.assertIn("BadZipFile", result.stdout)
            self.assertNotIn("FAILED - RETRYING", result.stdout)
            self.assertIn("failed=1", result.stdout)

    def test_wallet_retry_details_are_visible_before_success_at_normal_verbosity(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            shutil.copytree(ROOT / "playbooks/callback_plugins", work / "callback_plugins",
                            ignore=shutil.ignore_patterns("__pycache__"))
            helper = work / "wallet.py"
            helper.write_text('''import json, sys
from pathlib import Path
counter = Path(__file__).with_suffix('.count')
attempt = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(attempt))
if attempt < 3:
    print('SECRET-RAW-EXCEPTION', file=sys.stderr)
    print('APEXLANG_WALLET_ERROR ' + json.dumps({
        'stage': 'generate_wallet', 'error': 'ServiceError', 'http_status': 404,
        'code': 'NotAuthorizedOrNotFound'}), file=sys.stderr)
    sys.exit(1)
print('Wallet is ready')
''')
            original = yaml.safe_load((ROOT / "playbooks/site.yml").read_text())[0]
            task = next(item for item in original["tasks"] if "apexlang_wallet" in item.get("tags", []))
            task["ansible.builtin.command"]["argv"] = [sys.executable, str(helper)]
            task.update(retries=2, delay=0)
            play = [{"hosts": "all", "gather_facts": False, "vars": {
                "auto_wallet": True, "config_copy": {"changed": True},
                "wallet_marker": {"stat": {"exists": False}},
            }, "tasks": [task]}]
            playfile = work / "retry.yml"
            playfile.write_text(yaml.safe_dump(play))
            result = subprocess.run(
                [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", "-c", "local",
                 "-e", f"ansible_python_interpreter={sys.executable}", str(playfile)],
                env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(work / "ansible-temp"),
                     "ANSIBLE_NOCOLOR": "1", "ANSIBLE_VERBOSITY": "0", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("WALLET RETRY: stage=generate_wallet"), 2)
            self.assertIn("http_status=404 code=NotAuthorizedOrNotFound", result.stdout)
            self.assertNotIn("SECRET-RAW-EXCEPTION", result.stdout + result.stderr)
            self.assertIn("PLAY RECAP", result.stdout)
            self.assertEqual(helper.with_suffix(".count").read_text(), "3")

    def test_retry_callback_respects_no_log_and_ignores_unrelated_tasks(self):
        module = load_module("retry_callback", ROOT / "playbooks/callback_plugins/apexlang_retry.py")
        callback = module.CallbackModule()
        callback._display = mock.Mock()
        stderr = 'APEXLANG_WALLET_ERROR {"error": "SECRET"}'
        for tags, task_no_log, result_no_log in (([], False, False), (["apexlang_wallet"], True, False),
                                                (["apexlang_wallet"], False, True)):
            callback.v2_runner_retry(SimpleNamespace(
                task=SimpleNamespace(tags=tags, no_log=task_no_log),
                result={"stderr": stderr, "_ansible_no_log": result_no_log}))
        callback._display.display.assert_not_called()

    def test_runner_initializes_utf8_locale_before_starting_ansible(self):
        binary = Path(sys.executable).parent / "ansible-playbook"
        with tempfile.TemporaryDirectory() as folder:
            environment = {
                **os.environ, "LC_ALL": "C", "LANG": "C", "LC_CTYPE": "C",
                "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0",
                "ANSIBLE_LOCAL_TEMP": str(Path(folder) / "ansible-temp"),
            }
            before = subprocess.run([str(binary), "--version"], env=environment, text=True, capture_output=True)
            self.assertNotEqual(before.returncode, 0)
            self.assertIn("Ansible requires the locale encoding to be UTF-8", before.stderr)
            play = Path(folder) / "locale.yml"
            play.write_text("- hosts: all\n  gather_facts: false\n  tasks:\n"
                            "    - name: Verify UTF-8 output\n      ansible.builtin.debug:\n"
                            "        msg: locale-ready-日本語\n", encoding="utf-8")
            log = Path(folder) / "deploy.log"
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; configure_ansible_environment; shift; run_logged "$@"',
                 "test", str(ROOT / "scripts/run-ansible.sh"), str(log), str(binary),
                 "-i", "localhost,", "-c", "local", str(play)],
                env=environment, text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Ansible locale: en_US.UTF-8 (UTF-8)", result.stdout)
            self.assertIn("locale-ready-日本語", result.stdout)
            self.assertIn("PLAY RECAP", log.read_text(encoding="utf-8"))
            self.assertIn("locale-ready-日本語", log.read_text(encoding="utf-8"))

    def test_playbook_syntax_with_pinned_ansible(self):
        binary = Path(sys.executable).parent / "ansible-playbook"
        with tempfile.TemporaryDirectory() as folder:
            environment = {**os.environ, "ANSIBLE_LOCAL_TEMP": folder}
            result = subprocess.run([str(binary), "-i", "localhost,", "-c", "local", "--syntax-check",
                                     str(ROOT / "playbooks/site.yml")], env=environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_runner_preserves_failure_and_timeout_status_while_streaming_output(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "deploy.log"
            for code in (0, 2, 17, 124):
                result = subprocess.run(
                    ["bash", "-c", 'source "$1"; run_logged "$2" bash -c "$3"', "test",
                     str(ROOT / "scripts/run-ansible.sh"), str(log), f"echo visible-progress; exit {code}"],
                    text=True, capture_output=True)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn("visible-progress", result.stdout)
            self.assertEqual(log.read_text().count("visible-progress"), 4)

    def test_real_ansible_failure_is_logged_and_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            play = Path(folder) / "fail.yml"
            play.write_text("- hosts: all\n  gather_facts: false\n  tasks:\n"
                            "    - name: Visible task progress\n      ansible.builtin.debug:\n        msg: progress-visible\n"
                            "    - name: Deliberate verification failure\n      ansible.builtin.fail:\n        msg: expected-test-failure\n")
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; shift; run_logged "$@"', "test", str(ROOT / "scripts/run-ansible.sh"),
                 str(Path(folder) / "log"), str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(play)],
                env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(Path(folder) / "ansible-temp"), "ANSIBLE_NOCOLOR": "1"},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("PLAY RECAP", result.stdout)
            self.assertIn("progress-visible", result.stdout)
            self.assertIn("expected-test-failure", (Path(folder) / "log").read_text())

    def test_wallet_probe_selects_only_requested_alias_and_mtls_port(self):
        probe = load_module("probe", ROOT / "vm/verify-adb-network.py")
        tns = """other_low = (description=(address=(host=wrong.example)(port=1522)))
apexla1a2b3c4d_low =
 (description=(address=(host=correct.example)(port=1522)))
apexla1a2b3c4d_high = (description=(address=(host=high.example)(port=1522)))
"""
        self.assertEqual(probe.service_endpoint(tns, "apexla1a2b3c4d"), ("correct.example", 1522))
        for invalid in (tns.replace("port=1522", "port=1521"), tns.replace("apexla1a2b3c4d_low", "different_low")):
            with self.assertRaises(ValueError):
                probe.service_endpoint(invalid, "apexla1a2b3c4d")

    def test_configuration_retry_is_separate_from_vm_lifecycle(self):
        with (ROOT / "provisioning.tf").open() as stream:
            document = hcl2.load(stream)
        resources = {kind.strip('"') + "." + name.strip('"'): value
                     for block in document["resource"] for kind, instances in block.items()
                     for name, value in instances.items()}
        configure = resources["terraform_data.configure"]
        self.assertIn("triggers_replace", configure)
        self.assertIn("oci_identity_policy.wallet", str(configure["depends_on"]))
        self.assertIn("private_endpoint_reachable_ip", str(configure["connection"]))
        self.assertIn("tls_private_key.provisioner.private_key_openssh", str(configure["connection"]))
        with (ROOT / "compute.tf").open() as stream:
            compute = hcl2.load(stream)
        instance = next(value for block in compute["resource"] for kind, instances in block.items()
                        if kind.strip('"') == "oci_core_instance" for value in instances.values())
        self.assertNotIn("provisioner", instance)

    def test_ansible_waits_for_wallet_and_skips_it_only_when_explicitly_disabled(self):
        play = yaml.safe_load((ROOT / "playbooks/site.yml").read_text())[0]
        tasks = {task["name"]: task for task in play["tasks"]}
        wallet_task = tasks["Acquire this database wallet with bounded retries"]
        self.assertEqual(wallet_task["until"], "wallet_download.rc in [0, 2]")
        self.assertEqual(wallet_task["failed_when"], "wallet_download.rc != 0")
        self.assertIn("auto_wallet", wallet_task["when"])
        self.assertNotIn("ignore_errors", wallet_task)
        self.assertIn("--force", wallet_task["ansible.builtin.command"]["argv"])
        self.assertIn("adb_ocid", play["vars"]["application_config"])
        self.assertNotIn("adb_admin_password", (ROOT / "playbooks/site.yml").read_text())


class SourceTests(unittest.TestCase):
    def test_rm_ssh_path_is_internal_and_limited_to_the_vm(self):
        def resources(filename):
            with (ROOT / filename).open() as stream:
                document = hcl2.load(stream)
            return {kind.strip('"') + "." + name.strip('"'): value
                    for block in document["resource"] for kind, instances in block.items()
                    for name, value in instances.items()}
        network = resources("network.tf")
        rm = resources("provisioning.tf")
        ingress = network["oci_core_security_list.dev"]["ingress_security_rules"]
        management = next(rule for rule in ingress if "rm_subnet_cidr" in str(rule["source"]))
        options = management["tcp_options"][0]
        self.assertEqual((options["min"], options["max"]), (22, 22))
        egress = rm["oci_core_security_list.rm"]["egress_security_rules"]
        self.assertEqual(len(egress), 1)
        self.assertIn("oci_core_instance.dev.private_ip", egress[0]["destination"])
        self.assertIn("/32", egress[0]["destination"])
        self.assertTrue(rm["oci_core_subnet.rm"]["prohibit_public_ip_on_vnic"])
        for rule in ingress:
            if "0.0.0.0/0" in str(rule.get("source")):
                self.assertEqual(str(rule["protocol"]).strip('"'), "1")

    def test_public_routes_do_not_mix_internet_and_all_services_gateways(self):
        with (ROOT / "network.tf").open() as stream:
            network = hcl2.load(stream)
        route_tables = [table for block in network["resource"] for resource_type, resources in block.items()
                        if resource_type.strip('"') == "oci_core_route_table" for table in resources.values()]
        self.assertTrue(route_tables)
        for table in route_tables:
            targets = [rule["network_entity_id"] for rule in table["route_rules"]]
            has_internet = any("oci_core_internet_gateway." in target for target in targets)
            has_service = any("oci_core_service_gateway." in target for target in targets)
            self.assertFalse(has_internet and has_service, "OCI rejects IGW + All Services SGW in one route table")

    def test_shell_scripts_parse(self):
        for name in ("scripts/run-ansible.sh", "vm/adb-connect", "vm/apexlang-status"):
            subprocess.run(["bash", "-n", str(ROOT / name)], check=True)

    def test_resource_manager_form_covers_all_variables(self):
        with (ROOT / "variables.tf").open() as stream:
            terraform = hcl2.load(stream)
        names = {json.loads(name) if name.startswith('"') else name
                 for group in terraform["variable"] for name in group}
        schema = yaml.safe_load((ROOT / "schema.yaml").read_text())
        self.assertEqual(names, set(schema["variables"]))
        grouped = [name for group in schema["variableGroups"] for name in group["variables"]]
        self.assertCountEqual(grouped, list(names))


if __name__ == "__main__":
    unittest.main(verbosity=2)
