#!/opt/apexlang/venv/bin/python
"""Acquire a wallet without putting the wallet or its password in Terraform state/metadata."""
import argparse
import io
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import sys
import tempfile
import zipfile

CONFIG = Path("/etc/apexlang/config.json")
WALLET = Path("/home/opc/.adb/wallet.zip")
MARKER = Path("/var/lib/apexlang/wallet.ready")
MAX_WALLET_BYTES = 16 * 1024 * 1024


class WalletFailure(Exception):
    def __init__(self, stage, cause):
        super().__init__(stage)
        self.stage = stage
        self.cause = cause


def failure_summary(error):
    """Return diagnostic fields only; OCI exception text can contain credentials."""
    cause = error.cause if isinstance(error, WalletFailure) else error
    code = getattr(cause, "code", None)
    status = getattr(cause, "status", None)
    return {
        "stage": error.stage if isinstance(error, WalletFailure) else "local",
        "error": type(cause).__name__,
        "http_status": status if type(status) is int and 100 <= status <= 599 else None,
        "code": code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code) else None,
    }


def failure_exit_code(error):
    # A malformed wallet cannot be repaired by waiting for IAM propagation.
    if isinstance(error, zipfile.BadZipFile) or (isinstance(error, WalletFailure) and error.stage == "validate_wallet"):
        return 2
    return 1


def validate_wallet(payload):
    if len(payload) > MAX_WALLET_BYTES:
        raise ValueError("Wallet is unexpectedly large")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        if not {"tnsnames.ora", "cwallet.sso"}.issubset(names):
            raise ValueError("Wallet is missing tnsnames.ora or cwallet.sso")
        if sum(entry.file_size for entry in archive.infolist()) > MAX_WALLET_BYTES:
            raise ValueError("Expanded wallet is unexpectedly large")
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("Invalid path in wallet")
        if archive.testzip() is not None:
            raise ValueError("Wallet integrity check failed")


def save_wallet(payload, destination, uid, gid):
    """Validate first; an unsuccessful refresh must preserve the existing wallet."""
    validate_wallet(payload)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(destination.parent, uid, gid)
    os.chmod(destination.parent, 0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".wallet-", delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), uid, gid)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download_wallet(config):
    adb_ocid = config["adb_ocid"]
    if not adb_ocid:
        raise ValueError("ADB OCID is required")
    import oci

    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    except Exception as error:
        raise WalletFailure("instance_principal", error) from None
    try:
        client = oci.database.DatabaseClient({"region": config["region"]}, signer=signer, timeout=(15, 90))
        # The auto-login wallet is used by SQLcl. This random archive password is never persisted.
        details = oci.database.models.GenerateAutonomousDatabaseWalletDetails(
            password="Aa1!" + secrets.token_urlsafe(24), generate_type="SINGLE"
        )
        response = client.generate_autonomous_database_wallet(adb_ocid, details)
    except Exception as error:
        raise WalletFailure("generate_wallet", error) from None
    payload = bytearray()
    try:
        # Decode HTTP Content-Encoding (gzip/deflate) before validating the ZIP.
        # iter_content also handles a response already buffered by Requests.
        for chunk in response.data.iter_content(chunk_size=65536):
            payload.extend(chunk)
            if len(payload) > MAX_WALLET_BYTES:
                raise ValueError("Wallet download exceeded size limit")
    except Exception as error:
        raise WalletFailure("download_wallet", error) from None
    finally:
        response.data.close()
    try:
        validate_wallet(payload)
    except (zipfile.BadZipFile, ValueError) as error:
        raise WalletFailure("validate_wallet", error) from None
    return bytes(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-file", type=Path, help="Import a wallet downloaded through the OCI Console")
    parser.add_argument("--force", action="store_true", help="Replace an already installed wallet")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run using sudo")
    if WALLET.is_file() and MARKER.is_file() and not args.force:
        print("Wallet is already ready; use --force to refresh it.")
        return 0
    config = json.loads(CONFIG.read_text())
    if args.from_file:
        with args.from_file.open("rb") as stream:
            payload = stream.read(MAX_WALLET_BYTES + 1)
    else:
        if not config["auto_wallet"]:
            parser.error("Automatic wallet acquisition is disabled. Use --from-file.")
        payload = download_wallet(config)
    owner = pwd.getpwnam("opc")
    save_wallet(payload, WALLET, owner.pw_uid, owner.pw_gid)
    MARKER.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    MARKER.write_text("ready\n")
    MARKER.chmod(0o644)
    print("Wallet is ready. Use adb-connect ADMIN or adb-connect <workspace-schema>.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # OCI exceptions may contain request bodies; never log the full exception or wallet password.
        print("APEXLANG_WALLET_ERROR " + json.dumps(failure_summary(error)), file=sys.stderr)
        sys.exit(failure_exit_code(error))
