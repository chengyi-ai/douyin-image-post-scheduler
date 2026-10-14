import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


APPLY = load("apply_triage", ".github/scripts/apply_triage.py")
INTAKE = load("intake_feedback", ".github/scripts/intake_feedback.py")
SUBMIT = load("submit_feedback", "tools/submit_feedback.py")
VALIDATE = load("validate_repo", "tools/validate_repo.py")


def verdict(**overrides):
    data = {
        "decision": "accepted",
        "type": "bug",
        "size": "S",
        "risk": "low",
        "duplicate_of": None,
        "summary": "修复正文截断时没有优先停在句号处",
        "reasoning": "问题在 prepare_queue.py 的 fit_body_to_topics 句末判断。",
        "plan": ["调整 fit_body_to_topics 的截断位置", "补充测试"],
        "questions": [],
    }
    data.update(overrides)
    return data


class TriageTests(unittest.TestCase):
    def load_verdict(self, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "triage.json"
            path.write_text(json.dumps(verdict(**overrides)), encoding="utf-8")
            return APPLY.load_result(path)

    def test_collaborator_small_bug_is_auto_implemented(self):
        actions = APPLY.plan_actions(self.load_verdict(), "COLLABORATOR", "github", True)
        self.assertTrue(actions["implement"])
        self.assertIn("triage:accepted", actions["labels"])
        self.assertNotIn("status:awaiting-maintainer", actions["labels"])

    def test_outside_contributor_waits_for_maintainer(self):
        actions = APPLY.plan_actions(self.load_verdict(), "NONE", "github", True)
        self.assertFalse(actions["implement"])
        self.assertIn("status:awaiting-maintainer", actions["labels"])
        self.assertIn("agent:implement", actions["comment"])

    def test_intake_sources_are_trusted(self):
        actions = APPLY.plan_actions(self.load_verdict(), "NONE", "social", True)
        self.assertTrue(actions["implement"])

    def test_auto_implement_switch_off(self):
        actions = APPLY.plan_actions(self.load_verdict(), "OWNER", "github", False)
        self.assertFalse(actions["implement"])

    def test_large_or_high_risk_needs_human(self):
        for overrides in ({"size": "L"}, {"risk": "high"}, {"type": "question"}):
            with self.subTest(**overrides):
                actions = APPLY.plan_actions(self.load_verdict(**overrides), "OWNER", "github", True)
                self.assertFalse(actions["implement"])

    def test_invalid_fields_fall_back_to_conservative_values(self):
        result = self.load_verdict(size="XL", risk="none", type="layout", duplicate_of="12")
        self.assertEqual((result["size"], result["risk"], result["type"]), ("L", "high", "question"))
        self.assertIsNone(result["duplicate_of"])

    def test_invalid_decision_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load_verdict(decision="merge-now")

    def test_needs_info_lists_questions(self):
        actions = APPLY.plan_actions(
            self.load_verdict(decision="needs-info", questions=["用的是哪条命令？"]),
            "NONE",
            "github",
            True,
        )
        self.assertIn("- 用的是哪条命令？", actions["comment"])
        self.assertNotIn("status:awaiting-maintainer", actions["labels"])

    def test_comment_redacts_credentials(self):
        leaked = "sk-ant-api03-abcdefghijklmnop"
        with mock.patch.dict(os.environ, {"GH_TOKEN": "ghs_secretvalue123"}):
            actions = APPLY.plan_actions(
                self.load_verdict(summary=f"{leaked} ghs_secretvalue123"), "OWNER", "github", True
            )
        self.assertNotIn(leaked, actions["comment"])
        self.assertNotIn("ghs_secretvalue123", actions["comment"])
        self.assertIn("[REDACTED]", actions["comment"])


class IntakeTests(unittest.TestCase):
    def test_repository_dispatch_payload(self):
        item = INTAKE.normalize(
            "repository_dispatch",
            {"client_payload": {"source": "social", "platform": "抖音", "url": "https://x/1", "title": "希望每天条数可以按日期设置", "body": "周末想多发一条"}},
        )
        self.assertEqual(item["source"], "social")
        body = INTAKE.render_issue(item)
        self.assertIn("抖音", body)
        self.assertIn("> 周末想多发一条", body)

    def test_unknown_source_defaults_to_social(self):
        item = INTAKE.normalize("workflow_dispatch", {"inputs": {"source": "evil", "title": "t", "body": "b"}})
        self.assertEqual(item["source"], "social")

    def test_title_falls_back_to_first_body_line(self):
        item = INTAKE.normalize("repository_dispatch", {"client_payload": {"body": "第一行\n第二行"}})
        self.assertEqual(item["title"], "第一行")

    def test_empty_feedback_is_rejected(self):
        with self.assertRaises(ValueError):
            INTAKE.normalize("repository_dispatch", {"client_payload": {}})

    def test_discussion_event(self):
        event = {
            "discussion": {
                "category": {"name": "Ideas"},
                "html_url": "https://github.com/o/r/discussions/3",
                "user": {"login": "alice"},
                "title": "支持按编号范围续跑",
                "body": None,
            }
        }
        item = INTAKE.normalize("discussion", event)
        self.assertEqual((item["source"], item["author"]), ("community", "alice"))

    def test_long_text_is_clipped(self):
        item = INTAKE.normalize("repository_dispatch", {"client_payload": {"title": "x" * 200, "body": "y"}})
        self.assertEqual(len(item["title"]), INTAKE.MAX_TITLE)


class SubmitFeedbackTests(unittest.TestCase):
    def test_payload_shape(self):
        args = SUBMIT.argparse.Namespace(
            source="social", platform="微博", url="https://weibo.com/1", author="a", title="t", body="b"
        )
        payload = SUBMIT.build_payload(args)
        self.assertEqual(payload["event_type"], "feedback")
        self.assertEqual(payload["client_payload"]["platform"], "微博")


class ValidateRepoTests(unittest.TestCase):
    def test_repository_passes(self):
        self.assertEqual(VALIDATE.validate(), [])

    def test_missing_referenced_path_is_reported(self):
        errors = []
        with mock.patch.object(Path, "read_text", return_value="见 `skills/不存在.py` 和 `scripts/不存在.py`"):
            VALIDATE.check_referenced_paths(errors)
        self.assertTrue(any("skills/不存在.py" in e for e in errors))
        self.assertTrue(any("scripts/不存在.py" in e for e in errors))

    def test_removed_red_line_is_reported(self):
        errors = []
        with mock.patch.object(Path, "read_text", return_value="随便写点什么"):
            VALIDATE.check_red_lines(errors)
        self.assertTrue(any("不读取浏览器 Cookie" in e for e in errors))
        self.assertTrue(any("请求确认" in e for e in errors))

    def test_queue_script_must_stay_offline(self):
        for source in ("import urllib.request", "from playwright.sync_api import sync_playwright", "import subprocess"):
            with self.subTest(source=source):
                errors = []
                with mock.patch.object(Path, "read_text", return_value=source + "\n"):
                    VALIDATE.check_queue_script(errors)
                self.assertTrue(errors)
        errors = []
        with mock.patch.object(Path, "read_text", return_value="import json\nimport secrets\n"):
            VALIDATE.check_queue_script(errors)
        self.assertEqual(errors, [])

    def test_sensitive_files_are_reported(self):
        files = [
            "README.md",
            "skills/douyin-image-post-scheduler/scripts/prepare_queue.py",
            ".env",
            "cookies.json",
            "content/001_示例/01_图片内容/01_标题.jpg",
            "douyin-queue.json",
            "out/douyin-schedule-0901.md",
            "recording.mov",
        ]
        errors = []
        VALIDATE.check_sensitive_files(errors, files)
        flagged = {e.rsplit("：", 1)[-1] for e in errors}
        self.assertEqual(flagged, set(files[2:]))


class LabelConfigTests(unittest.TestCase):
    def test_every_label_used_by_scripts_is_defined(self):
        defined = {label["name"] for label in json.loads((ROOT / ".github/labels.json").read_text(encoding="utf-8"))}
        required = {"needs-triage", "agent:implement", "agent:in-progress", "agent:pr-open", "agent:failed", "agent-pr"}
        required |= {f"triage:{d}" for d in APPLY.DECISIONS}
        required |= {f"type:{t}" for t in APPLY.TYPES}
        required |= {f"size:{s}" for s in APPLY.SIZES}
        required |= {f"risk:{r}" for r in APPLY.RISKS}
        required |= {"agent:skip", "status:awaiting-maintainer"}
        required |= {f"source:{s}" for s in INTAKE.SOURCES}
        self.assertEqual(required - defined, set())


class OpenAgentPrTests(unittest.TestCase):
    SCRIPT = (ROOT / ".github/scripts/open_agent_pr.sh").read_text(encoding="utf-8")

    def forbidden(self):
        match = re.search(r"^FORBIDDEN_RE='([^']+)'$", self.SCRIPT, re.M)
        self.assertIsNotNone(match, "open_agent_pr.sh 里找不到 FORBIDDEN_RE")
        return re.compile(match.group(1), re.I)

    def test_forbidden_paths(self):
        pattern = self.forbidden()
        blocked = [
            ".github/workflows/ci.yml",
            ".github/agent/implement.md",
            "LICENSE",
            ".gitignore",
            ".env",
            "config/.env.local",
            "Cookies.txt",
            "state/storage_state.json",
            "capture.har",
            "douyin-queue.json",
            "plans/douyin-schedule.md",
            "content/001_x/01_图片内容/01_标题.JPG",
            "demo.mov",
        ]
        allowed = [
            "README.md",
            "CLAUDE.md",
            "docs/agent-workflow.md",
            "skills/douyin-image-post-scheduler/SKILL.md",
            "skills/douyin-image-post-scheduler/scripts/prepare_queue.py",
            "skills/douyin-image-post-scheduler/references/browser-workflow.md",
            "tests/test_prepare_queue.py",
            "tools/validate_repo.py",
        ]
        for path in blocked:
            with self.subTest(blocked=path):
                self.assertIsNotNone(pattern.search(path))
        for path in allowed:
            with self.subTest(allowed=path):
                self.assertIsNone(pattern.search(path))

    def test_validator_and_pr_script_agree_on_sensitive_files(self):
        pattern = self.forbidden()
        for path in (".env", "cookies.json", "douyin-queue.json", "a.png", "b.mp4", "x.har"):
            with self.subTest(path=path):
                self.assertIsNotNone(VALIDATE.SENSITIVE_PATTERN.search(path))
                self.assertIsNotNone(pattern.search(path))

    def test_dispatched_workflows_accept_manual_runs(self):
        workflows = re.findall(r"gh workflow run (\S+)", self.SCRIPT)
        self.assertIn("ci.yml", workflows)
        for name in workflows:
            with self.subTest(workflow=name):
                path = ROOT / ".github/workflows" / name
                self.assertTrue(path.is_file(), f"{name} 不存在")
                self.assertIn("workflow_dispatch:", path.read_text(encoding="utf-8"))

    def test_ci_and_agent_run_the_same_checks(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for command in (
            "python tools/validate_repo.py",
            "python -m unittest discover -s tests",
            "python skills/douyin-image-post-scheduler/scripts/prepare_queue.py --help",
        ):
            with self.subTest(command=command):
                self.assertIn(command, ci)
                self.assertIn(command, self.SCRIPT)


if __name__ == "__main__":
    unittest.main()
