#!/usr/bin/env python3
"""仓库不变量检查：Skill 元数据、文档里引用的路径、红线声明、队列脚本的边界、敏感文件和标签配置。

只读，只用标准库。队列生成的行为测试在 tests/ 里。
"""

import ast
import json
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "douyin-image-post-scheduler"
SKILL_DIR = Path("skills") / SKILL_NAME
QUEUE_SCRIPT = SKILL_DIR / "scripts" / "prepare_queue.py"
REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "CLAUDE.md",
    "docs/agent-workflow.md",
    ".github/labels.json",
    str(SKILL_DIR / "SKILL.md"),
    str(SKILL_DIR / "VERSION"),
    str(SKILL_DIR / "agents" / "openai.yaml"),
    str(SKILL_DIR / "references" / "browser-workflow.md"),
    str(QUEUE_SCRIPT),
)

# 文档里用反引号或 Markdown 链接引用的仓库内路径，必须真实存在。
# 仓库根目录的文档相对仓库根解析；SKILL.md 相对 Skill 目录解析（安装后 Skill 目录就是根）。
ROOT_PREFIXES = ("skills/", "tests/", "tools/", "docs/", ".github/")
SKILL_PREFIXES = ("scripts/", "references/", "agents/")
ROOT_DOCS = ("README.md", "CLAUDE.md", "docs/agent-workflow.md")

# 红线声明不能被悄悄删掉：发布前确认、不碰账号凭据、不绕过验证、脚本不发布。
REQUIRED_PHRASES = {
    "README.md": ("实际对外发布需要用户确认", "不读取浏览器 Cookie", "不绕过验证码"),
    str(SKILL_DIR / "SKILL.md"): ("请求确认", "不打开浏览器、不上传、不发布", "验证码", "任一验证失败都不得点击发布"),
}

# 队列脚本只读素材、只写计划文件：不准引入浏览器自动化、网络或子进程。
FORBIDDEN_IMPORTS = {
    "selenium",
    "playwright",
    "pyppeteer",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
    "http",
    "socket",
    "ssl",
    "webbrowser",
    "subprocess",
    "browser_cookie3",
    "sqlite3",
}

# 仓库里不放账号凭据、登录态、素材、录屏和排期结果。
SENSITIVE_PATTERN = re.compile(
    r"(^|/)\.env|cookie|storage[-_]?state|\.har$|(^|/)douyin-(queue|schedule)[^/]*$"
    r"|\.(jpe?g|png|webp|gif|heic|mov|mp4|zip)$",
    re.I,
)


def path_pattern(prefixes):
    return re.compile(r"(?:`|\]\()((?:%s)[^`)\s]*)" % "|".join(re.escape(p) for p in prefixes))


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def check_skill(errors):
    text = read(SKILL_DIR / "SKILL.md")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        errors.append("SKILL.md 缺少 YAML frontmatter")
        return
    meta = dict(line.split(":", 1) for line in match.group(1).splitlines() if ":" in line)
    if meta.get("name", "").strip() != SKILL_NAME:
        errors.append(f"SKILL.md 的 name 必须是 {SKILL_NAME}")
    if len(meta.get("description", "").strip()) < 20:
        errors.append("SKILL.md 的 description 过短或缺失")

    version = read(SKILL_DIR / "VERSION").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append(f"VERSION 不是 X.Y.Z 格式：{version!r}")

    if f"${SKILL_NAME}" not in read(SKILL_DIR / "agents" / "openai.yaml"):
        errors.append(f"agents/openai.yaml 的 default_prompt 应引用 ${SKILL_NAME}")


def check_referenced_paths(errors):
    def scan(doc, base, prefixes):
        for raw in path_pattern(prefixes).findall(read(doc)):
            path = raw.split("#", 1)[0].rstrip("/.,，。")
            if any(ch in path for ch in "*{<"):
                continue
            if not (ROOT / base / path).exists():
                errors.append(f"{doc} 引用的路径不存在：{path}")

    for doc in ROOT_DOCS:
        scan(doc, Path("."), ROOT_PREFIXES)
    scan(SKILL_DIR / "SKILL.md", SKILL_DIR, SKILL_PREFIXES)


def check_red_lines(errors):
    for doc, phrases in REQUIRED_PHRASES.items():
        text = read(doc)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{doc} 缺少红线声明：{phrase}")


def check_queue_script(errors):
    tree = ast.parse(read(QUEUE_SCRIPT), filename=str(QUEUE_SCRIPT))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            if name.split(".", 1)[0] in FORBIDDEN_IMPORTS:
                errors.append(f"{QUEUE_SCRIPT} 不应引入 {name}：脚本只读素材、只写计划文件")


def tracked_files():
    try:
        output = subprocess.run(
            ["git", "-c", "core.quotePath=false", "ls-files"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [line for line in output.splitlines() if line]


def check_sensitive_files(errors, files=None):
    files = tracked_files() if files is None else files
    if files is None:
        return  # 不在 git 仓库里（例如解压的发布包），跳过。
    for path in files:
        if SENSITIVE_PATTERN.search(path):
            errors.append(f"仓库里不应包含账号凭据、素材、录屏或排期结果：{path}")


def check_python(errors):
    files = sorted(ROOT.glob("skills/*/scripts/*.py")) + sorted(ROOT.glob("tools/*.py"))
    files += sorted(ROOT.glob(".github/scripts/*.py")) + sorted(ROOT.glob("tests/*.py"))
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(files):
            try:
                py_compile.compile(str(path), cfile=str(Path(tmp) / f"{i}.pyc"), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"语法错误：{path.relative_to(ROOT)}：{exc.msg.strip()}")


def check_labels(errors):
    labels = json.loads(read(".github/labels.json"))
    names = [label["name"] for label in labels]
    if len(names) != len(set(names)):
        errors.append(".github/labels.json 有重名标签")
    for label in labels:
        if not re.fullmatch(r"[0-9a-f]{6}", label.get("color", "")):
            errors.append(f"标签颜色不是 6 位十六进制：{label['name']}")


def validate():
    errors = [f"缺少文件：{name}" for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    if errors:
        return errors
    for check in (
        check_skill,
        check_referenced_paths,
        check_red_lines,
        check_queue_script,
        check_sensitive_files,
        check_python,
        check_labels,
    ):
        check(errors)
    return errors


def main():
    errors = validate()
    for error in errors:
        print(f"✗ {error}", file=sys.stderr)
    if errors:
        return 1
    print("✓ 仓库检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
