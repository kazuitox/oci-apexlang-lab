#!/usr/bin/env python3
"""Check the selected wallet service and its TCP endpoint without a DB password."""
import json
from pathlib import Path
import re
import socket
import zipfile


def service_endpoint(tns, db_name):
    # Wallet tnsnames entries can span multiple lines; isolate the exact alias.
    alias = re.escape(db_name + "_low")
    match = re.search(r"(?im)^\s*" + alias + r"\s*=\s*(.*?)(?=^\s*[a-z0-9_]+\s*=|\Z)", tns, re.S | re.M)
    if not match:
        raise ValueError("The expected low service is absent from this wallet")
    host = re.search(r"\(\s*host\s*=\s*([a-zA-Z0-9.-]+)\s*\)", match.group(1), re.I)
    port = re.search(r"\(\s*port\s*=\s*([0-9]+)\s*\)", match.group(1), re.I)
    if not host or not port or int(port.group(1)) != 1522:
        raise ValueError("The wallet does not contain the expected mTLS TCP endpoint")
    return host.group(1), int(port.group(1))


def main():
    config = json.loads(Path("/etc/apexlang/config.json").read_text())
    with zipfile.ZipFile("/home/opc/.adb/wallet.zip") as archive:
        endpoint = service_endpoint(archive.read("tnsnames.ora").decode(), config["adb_name"])
    with socket.create_connection(endpoint, timeout=15):
        print(f"ADB wallet service and TCP {endpoint[1]} connectivity: OK (DB login not tested)")


if __name__ == "__main__":
    main()
