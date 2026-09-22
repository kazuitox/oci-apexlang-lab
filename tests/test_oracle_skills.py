"""Exercise the production skill tasks against local Git repositories, without OCI/network access."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def skill_tasks():
    tasks = yaml.safe_load((ROOT / "playbooks/tools.yml").read_text())
    start = next(i for i, task in enumerate(tasks) if task["name"] == "Install Oracle APEXlang skills")
    end = next(i for i, task in enumerate(tasks) if task["name"] == "Install interactive shell environment")
    selected = copy.deepcopy(tasks[start:end])
    # Run as the current test user, leaving the Git, verification and registration logic unchanged.
    for task in selected:
        task.pop("become", None)
        task.pop("become_user", None)
        module = task.get("ansible.builtin.file", {})
        module.pop("owner", None)
        module.pop("group", None)
    return selected


def run_skill_play(work, repo, revision, tasks=None):
    home = work / "home"
    for directory in (home / ".local/share", home / ".agents/skills", work / "state"):
        directory.mkdir(parents=True, exist_ok=True)
    playfile = work / "skills.yml"
    playfile.write_text(yaml.safe_dump([{
        "hosts": "all", "gather_facts": False,
        "vars": {"dev_home": str(home), "state_dir": str(work / "state"),
                 "oracle_skills_url": repo, "oracle_skills_revision": revision},
        "tasks": skill_tasks() if tasks is None else tasks,
    }]))
    return subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", "-c", "local",
         "-e", f"ansible_python_interpreter={sys.executable}", str(playfile)],
        env={**os.environ, "ANSIBLE_LOCAL_TEMP": str(work / "ansible-local"),
             "ANSIBLE_REMOTE_TEMP": str(work / "ansible-remote"), "ANSIBLE_NOCOLOR": "1",
             "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
        text=True, capture_output=True, timeout=120)


class OracleSkillsTests(unittest.TestCase):
    def git(self, *args):
        return subprocess.run(
            ["git", *map(str, args)], check=True, text=True, capture_output=True,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                 "GIT_AUTHOR_NAME": "Skill Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                 "GIT_COMMITTER_NAME": "Skill Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"},
            timeout=30).stdout.strip()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apexlang-skills-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.remote = self.work / "upstream"
        self.git("init", "--initial-branch=legacy-default", self.remote)
        (self.remote / "README.md").write_text("Default branch without APEXlang\n")
        self.git("-C", self.remote, "add", ".")
        self.git("-C", self.remote, "commit", "-m", "legacy default")
        self.legacy_revision = self.git("-C", self.remote, "rev-parse", "HEAD")
        self.git("-C", self.remote, "checkout", "-b", "main")
        skill = self.remote / "apex/apexlang/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: apexlang\n---\nPinned skill fixture\n")
        helper = skill.parent / "tools/helper.txt"
        helper.parent.mkdir()
        helper.write_text("Supporting files stay with the skill\n")
        self.git("-C", self.remote, "add", ".")
        self.git("-C", self.remote, "commit", "-m", "known skill version")
        self.revision = self.git("-C", self.remote, "rev-parse", "HEAD")
        # The pin is deliberately no longer the main tip, testing shallow fetch by SHA.
        skill.write_text("New unverified upstream skill\n")
        self.git("-C", self.remote, "commit", "-am", "later main version")
        self.git("-C", self.remote, "checkout", "legacy-default")
        self.url = self.remote.as_uri()
        self.checkout = self.work / "home/.local/share/oracle-skills"
        self.link = self.work / "home/.agents/skills/apexlang"
        self.record = self.work / "state/oracle-skills-commit.txt"

    def assert_ready(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("-C", self.checkout, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(self.record.read_text().strip(), self.revision)
        self.assertTrue(self.link.is_symlink())
        self.assertIn("Pinned skill fixture", (self.link / "SKILL.md").read_text())
        self.assertTrue((self.link / "tools/helper.txt").is_file())
        self.assertIn("checked_out=" + self.revision, result.stdout)

    def test_fresh_install_uses_pin_despite_default_branch_and_main_changes(self):
        self.assert_ready(run_skill_play(self.work, self.url, self.revision))
        result = run_skill_play(self.work, self.url, self.revision)
        self.assert_ready(result)
        self.assertIn("changed=0", result.stdout)

    def test_recovers_existing_shallow_clone_of_wrong_default_branch(self):
        self.checkout.parent.mkdir(parents=True)
        self.git("clone", "--depth", "1", self.url, self.checkout)
        self.assertEqual(self.git("-C", self.checkout, "rev-parse", "--is-shallow-repository"), "true")
        self.assertFalse((self.checkout / "apex/apexlang/SKILL.md").exists())
        # Reproduce the old failure using the old Git options and the old assertion.
        old = skill_tasks()
        old_git = old[0]["ansible.builtin.git"]
        old_git.pop("version")
        old_git.pop("refspec")
        old_git["update"] = False
        assertion = next(task for task in old if task["name"] == "Require the APEXlang skill")
        assertion["ansible.builtin.assert"]["that"] = "skill_file.stat.isreg | default(false)"
        failed = run_skill_play(self.work, self.url, self.revision, old)
        self.assertEqual(failed.returncode, 2, failed.stdout + failed.stderr)
        self.assertIn("Require the APEXlang skill", failed.stdout)
        self.assertFalse(self.link.exists())
        self.assertFalse(self.record.exists())
        self.assert_ready(run_skill_play(self.work, self.url, self.revision))

    def test_local_edits_are_preserved_and_block_checkout(self):
        self.checkout.parent.mkdir(parents=True)
        self.git("clone", "--depth", "1", self.url, self.checkout)
        edited = self.checkout / "README.md"
        edited.write_text("User edit to preserve\n")
        result = run_skill_play(self.work, self.url, self.revision)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Local modifications", result.stdout + result.stderr)
        self.assertEqual(edited.read_text(), "User edit to preserve\n")
        self.assertEqual(self.git("-C", self.checkout, "rev-parse", "HEAD"), self.legacy_revision)
        self.assertFalse(self.link.exists())
        self.assertFalse(self.record.exists())

    def test_missing_skill_reports_revision_and_path_without_registering(self):
        result = run_skill_play(self.work, self.url, self.legacy_revision)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("APEXlang skill verification failed", result.stdout)
        self.assertIn(self.legacy_revision, result.stdout)
        self.assertIn("apex/apexlang/SKILL.md", result.stdout)
        self.assertFalse(self.link.exists())
        self.assertFalse(self.record.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
