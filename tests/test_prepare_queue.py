from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "douyin-image-post-scheduler" / "scripts" / "prepare_queue.py"


class PrepareQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "content"
        self.root.mkdir()
        for number in range(1, 5):
            self._create_post(number)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_post(self, number: int) -> None:
        post = self.root / f"{number:03d}_示例内容"
        images = post / "01_图片内容"
        images.mkdir(parents=True)
        for image_number in range(1, 9):
            title = f"示例标题{number}" if image_number == 1 else f"示例图片{image_number}"
            (images / f"{image_number:02d}_{title}.jpg").write_bytes(b"")
        (post / "02_文字内容.txt").write_text(
            "这是一个完整句子。" * 180, encoding="utf-8"
        )
        (post / "03_标题内容.txt").write_text(
            f"第{number}条素材长标题", encoding="utf-8"
        )
        (post / "04_标签内容.txt").write_text(
            "#人工智能 #内容创作 #工作流 #自动化 #创作者 #备用标签",
            encoding="utf-8",
        )

    def _run(self, output: Path, seed: int = 12345) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.root),
                "--start-date",
                "2026-09-01",
                "--posts-per-day",
                "2",
                "--seed",
                str(seed),
                "--json-output",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_queue_constraints_and_schedule(self) -> None:
        output = Path(self.temp_dir.name) / "queue.json"
        result = self._run(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["items"]), 4)
        self.assertEqual(payload["seed"], 12345)

        days: dict[str, list[datetime]] = defaultdict(list)
        for item in payload["items"]:
            self.assertEqual(len(item["images"]), 8)
            self.assertEqual(len(item["tags"]), 5)
            self.assertLessEqual(len(item["title"]), 20)
            topic_size = sum(len(tag) for tag in item["tags"]) + 20
            self.assertLessEqual(len(item["body"]) + topic_size, 990)
            timestamp = datetime.strptime(item["schedule"], "%Y-%m-%d %H:%M")
            days[item["schedule"][:10]].append(timestamp)

        self.assertEqual(sorted(map(len, days.values())), [2, 2])
        for times in days.values():
            self.assertGreaterEqual((times[1] - times[0]).total_seconds(), 5400)
            self.assertTrue(all(9 <= timestamp.hour <= 22 for timestamp in times))

    def test_seed_is_reproducible(self) -> None:
        first = Path(self.temp_dir.name) / "first.json"
        second = Path(self.temp_dir.name) / "second.json"
        self.assertEqual(self._run(first).returncode, 0)
        self.assertEqual(self._run(second).returncode, 0)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_missing_image_fails_without_queue(self) -> None:
        missing = self.root / "001_示例内容" / "01_图片内容" / "08_示例图片8.jpg"
        missing.unlink()
        output = Path(self.temp_dir.name) / "invalid.json"
        result = self._run(output)
        self.assertEqual(result.returncode, 2)
        self.assertIn("图片数量", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
