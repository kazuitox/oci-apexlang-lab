"""Show sanitized wallet diagnostics during Ansible retries at normal verbosity."""
import json
import re

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "apexlang_retry"
    CALLBACK_NEEDS_ENABLED = False

    def v2_runner_retry(self, result):
        data = result.result
        if data.get("_ansible_no_log") or result.task.no_log:
            return
        if "apexlang_wallet" not in result.task.tags:
            return
        for line in data.get("stderr", "").splitlines():
            prefix = "APEXLANG_WALLET_ERROR "
            if not line.startswith(prefix):
                continue
            try:
                summary = json.loads(line[len(prefix):])
            except (ValueError, TypeError):
                continue
            if not isinstance(summary, dict):
                continue
            fields = []
            for key in ("stage", "error", "http_status", "code"):
                value = str(summary.get(key))
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
                    value = "unavailable"
                fields.append(f"{key}={value}")
            self._display.display("WALLET RETRY: " + " ".join(fields))
