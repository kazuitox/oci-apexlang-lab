#!/usr/bin/env python3
"""Run bounded SQLcl bootstrap stages; never print SQL, credentials or raw errors."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile

STEPS = ("preflight", "schema", "workspace", "account", "verify")
CONFIG = Path("/etc/apexlang/config.json")
SQL_DIR = Path("/opt/apexlang/bootstrap-sql")
SQLCL = "/usr/local/bin/sql"
WALLET = "/home/opc/.adb/wallet.zip"


def validate_inputs(config, password):
    if not re.fullmatch(r"[a-z][a-z0-9]{0,13}", config["adb_name"]):
        raise ValueError("Invalid database name")
    if any(config[key] != "APEXLAB" for key in ("apex_schema", "apex_workspace", "apex_user")):
        raise ValueError("Unexpected bootstrap identity")
    if not isinstance(password, str) or not 12 <= len(password) <= 30:
        raise ValueError("Invalid password length")
    if any(ord(c) < 32 or ord(c) == 127 or c == '"' for c in password):
        raise ValueError("Invalid password character")
    if any(name in password.lower() for name in ("admin", "apexlab")):
        raise ValueError("Password contains username")
    if not all(re.search(pattern, password) for pattern in ("[A-Z]", "[a-z]", "[0-9]")):
        raise ValueError("Invalid password complexity")


def build_script(step, config, password, template, marker):
    validate_inputs(config, password)
    # Double quotes are rejected before building SQLcl's quoted password. SQL literals
    # use doubled apostrophes; DEFINE OFF prevents & expansion. No shell is involved.
    password_literal = "'" + password.replace("'", "''") + "'"
    body = template.replace("@@PASSWORD_LITERAL@@", password_literal)
    user = "APEXLAB" if step == "verify" else "ADMIN"
    return f"""set echo off
set verify off
set define off
set sqlblanklines on
set feedback off
set serveroutput on
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set cloudconfig {WALLET}
connect {user}/"{password}"@{config['adb_name']}_low
{body}
commit;
begin
  dbms_output.put_line('{marker}');
end;
/
exit success
"""


def execute_sqlcl(script, home, env, timeout=180):
    # Kill the entire launcher/JVM process group on timeout before deleting its home.
    with subprocess.Popen([SQLCL, "-s", "-L", "/nolog"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          cwd=home, env=env, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(script, timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def run_step(step, config, password, template):
    marker = "APEXLANG_OK_" + secrets.token_hex(16)
    script = build_script(step, config, password, template, marker)
    # SQLcl may write history/preferences/wallet extraction files. Isolate all of
    # them from opc's interactive home and delete this directory even on failure.
    ram_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None
    with tempfile.TemporaryDirectory(prefix="apexlang-sqlcl-", dir=ram_dir) as home:
        env = os.environ.copy()
        env.update(HOME=home, SQLPATH=home, JAVA_HOME="/opt/apexlang/jdk",
                   JAVA_TOOL_OPTIONS=f"-Duser.home={home}", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
        result = execute_sqlcl(script, home, env)
    lines = {line.strip() for line in result.stdout.splitlines()}
    # Only error identifiers are exported. Error text often echoes the SQL/password.
    codes = sorted(set(re.findall(r"(?m)^\s*(?:Error Message\s*=\s*)?((?:ORA|PLS|SP2)-[0-9]{4,5})\b",
                                  result.stdout + "\n" + result.stderr)))
    ok = result.returncode == 0 and marker in lines and not codes
    return {"stage": step, "ok": ok, "changed": ok and "APEXLANG_CHANGED" in lines,
            "codes": codes, "error": None if ok else "sqlcl_failed_or_incomplete"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=STEPS)
    args = parser.parse_args()
    try:
        # Ansible supplies JSON through stdin, never a password argument or environment variable.
        password = json.loads(sys.stdin.read())["password"]
        config = json.loads(CONFIG.read_text())
        template = (SQL_DIR / f"bootstrap-{args.step}.sql").read_text()
        result = run_step(args.step, config, password, template)
    except subprocess.TimeoutExpired:
        result = {"stage": args.step, "ok": False, "changed": False, "codes": [], "error": "timeout"}
    except Exception:
        # Do not expose exception text, subprocess input/output or JSON contents.
        result = {"stage": args.step, "ok": False, "changed": False, "codes": [], "error": "bootstrap_input_or_execution_failed"}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
