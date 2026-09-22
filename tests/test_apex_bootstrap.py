"""Bootstrap credential transport, fail-closed execution and real Ansible logging tests."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bootstrap", ROOT / "vm/bootstrap-apex.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
CONFIG = {"adb_name": "apexla12345678", "apex_schema": "APEXLAB",
          "apex_workspace": "APEXLAB", "apex_user": "APEXLAB"}
PASSWORD = "Test72'&/!$`\\;Secret"


class BootstrapTests(unittest.TestCase):
    def test_special_characters_are_sql_escaped_without_shell_expansion(self):
        for step in bootstrap.STEPS:
            template = (ROOT / f"sql/bootstrap-{step}.sql").read_text()
            script = bootstrap.build_script(step, CONFIG, PASSWORD, template, "test_marker")
            self.assertIn('set define off', script)
            self.assertIn('whenever sqlerror exit failure rollback', script)
            user = 'APEXLAB' if step == 'verify' else 'ADMIN'
            self.assertIn(f'connect {user}/"{PASSWORD}"@apexla12345678_low', script)
            self.assertNotIn('@@PASSWORD_LITERAL@@', script)
            if step in ('schema', 'account'):
                self.assertIn("'Test72''&/!$`\\;Secret'", script)

    def test_rejects_command_breaking_passwords_and_config(self):
        for password in ('BadQuote72"xx', 'BadNewline72\nxx', 'BadTab72\txxx',
                         'APEXLABpass72!', 'SomeADMIN72!', 'short'):
            with self.subTest(kind='invalid_password'), self.assertRaises(ValueError):
                bootstrap.validate_inputs(CONFIG, password)
        with self.assertRaises(ValueError):
            bootstrap.validate_inputs(dict(CONFIG, adb_name='bad\nprompt injected'), PASSWORD)
        with self.assertRaises(ValueError):
            bootstrap.validate_inputs(dict(CONFIG, apex_schema='ADMIN'), PASSWORD)

    def test_success_requires_real_marker_and_no_error_even_for_exit_zero(self):
        for mode in ('success', 'no_marker', 'error', 'connection_error', 'nonzero'):
            homes = []
            def fake(script, home, env):
                homes.append(home)
                self.assertEqual(env['HOME'], home)
                self.assertEqual(env['JAVA_TOOL_OPTIONS'], f'-Duser.home={home}')
                self.assertNotIn(PASSWORD, json.dumps(env))
                Path(home, 'history').write_text(PASSWORD)
                marker = re.search(r'APEXLANG_OK_[a-f0-9]+', script).group()
                output = ('APEXLANG_CHANGED\n' + marker + '\n') if mode != 'no_marker' else ''
                if mode == 'error':
                    output += 'ORA-01017: ' + PASSWORD + '\n'
                if mode == 'connection_error':
                    output += 'Error Message = ORA-01017: ' + PASSWORD + '\n'
                return subprocess.CompletedProcess([], 1 if mode == 'nonzero' else 0, output, '')
            with self.subTest(mode=mode), mock.patch.object(bootstrap, 'execute_sqlcl', side_effect=fake):
                result = bootstrap.run_step('preflight', CONFIG, PASSWORD, 'begin null; end;\n/')
            self.assertEqual(result['ok'], mode == 'success')
            self.assertEqual(result['changed'], mode == 'success')
            self.assertNotIn(PASSWORD, json.dumps(result))
            if mode in ('error', 'connection_error'):
                self.assertEqual(result['codes'], ['ORA-01017'])
            self.assertFalse(Path(homes[0]).exists())

    def test_timeout_removes_sqlcl_history_home(self):
        homes = []
        def timeout(script, home, env):
            homes.append(home)
            Path(home, 'history').write_text(PASSWORD)
            raise subprocess.TimeoutExpired(['sql'], 180, output=PASSWORD)
        with mock.patch.object(bootstrap, 'execute_sqlcl', side_effect=timeout), self.assertRaises(subprocess.TimeoutExpired):
            bootstrap.run_step('schema', CONFIG, PASSWORD, 'begin null; end;\n/')
        self.assertFalse(Path(homes[0]).exists())

    def test_command_has_no_password_arguments_and_receives_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder, 'sql')
            fake.write_text('#!/usr/bin/env python3\nimport sys\nassert sys.argv[1:] == ["-s", "-L", "/nolog"]\nprint(len(sys.stdin.read()))\n')
            fake.chmod(0o700)
            with mock.patch.object(bootstrap, 'SQLCL', str(fake)):
                result = bootstrap.execute_sqlcl(PASSWORD, folder, os.environ.copy())
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), str(len(PASSWORD)))

    def test_runner_removes_uploaded_and_runtime_secret_on_early_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            source = (ROOT / 'scripts/run-ansible.sh').read_text()
            source = source.replace('/run/apexlang-init.', str(work / 'runtime-'))
            source = source.replace('/var/lib/apexlang', str(work / 'state'))
            runner = work / 'runner.sh'
            runner.write_text(source)
            (work / 'bootstrap-secrets.json').write_text(json.dumps({'password': PASSWORD}))
            # Simulate an OS initialization failure; never touch system directories or install packages.
            command = '''source "$1"
id() { echo 0; }
flock() { return 0; }
install() { cp "${@: -2}"; }
timeout() { return 23; }
main
'''
            result = subprocess.run(['bash', '-c', command, 'test', str(runner)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            self.assertNotIn(PASSWORD, result.stdout + result.stderr)
            self.assertFalse((work / 'bootstrap-secrets.json').exists())
            self.assertEqual(list(work.glob('runtime-*')), [])


class BootstrapAnsibleTests(unittest.TestCase):
    def test_stages_stream_safe_progress_and_stop_before_ready_on_failure(self):
        ansible = str(Path(sys.executable).with_name('ansible-playbook'))
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                work = Path(folder)
                secret_file = work / 'secrets.json'
                secret_file.write_text(json.dumps({'password': PASSWORD}))
                fake = work / 'fake.py'
                fake.write_text('''import json, sys
password = json.load(sys.stdin)['password']
step = sys.argv[1]
fail = ''' + repr(failure) + ''' and step == 'workspace'
print(json.dumps({'ok': not fail, 'changed': step == 'schema',
                  'codes': ['ORA-01017'] if fail else [], 'error': password if fail else None}))
sys.exit(1 if fail else 0)
''')
                tasks = yaml.safe_load((ROOT / 'playbooks/apex-step.yml').read_text())
                tasks[0]['become'] = False
                tasks[0]['ansible.builtin.command']['argv'] = [sys.executable, str(fake), '{{ apex_stage }}']
                (work / 'step.yml').write_text(yaml.safe_dump(tasks, sort_keys=False))
                play = [{'hosts': 'all', 'gather_facts': False,
                         'vars': {'dev_home': folder, 'bootstrap_secrets_file': str(secret_file)},
                         'tasks': [{'name': 'Bootstrap stages', 'ansible.builtin.include_tasks': str(work / 'step.yml'),
                                    'loop': list(bootstrap.STEPS), 'loop_control': {'loop_var': 'apex_stage'}},
                                   {'name': 'Ready', 'ansible.builtin.copy': {'content': 'ready', 'dest': str(work / 'ready')}}]}]
                play_file = work / 'play.yml'
                play_file.write_text(yaml.safe_dump(play, sort_keys=False))
                env = dict(os.environ, LANG='en_US.UTF-8', LC_ALL='en_US.UTF-8', ANSIBLE_NOCOLOR='1',
                           ANSIBLE_LOCAL_TEMP=str(work / 'local'), ANSIBLE_REMOTE_TEMP=str(work / 'remote'))
                result = subprocess.run([ansible, '-i', 'localhost,', '-c', 'local',
                                         '-e', f'ansible_python_interpreter={sys.executable}', str(play_file)],
                                        text=True, capture_output=True, env=env)
                output = result.stdout + result.stderr
                self.assertNotIn(PASSWORD, output)
                self.assertIn('APEX schema', output)
                self.assertEqual(result.returncode == 0, not failure, output)
                self.assertEqual((work / 'ready').exists(), not failure)
                if failure:
                    self.assertIn('ORA-01017', output)
                    self.assertNotIn('APEX account - execute', output)


if __name__ == '__main__':
    unittest.main()
