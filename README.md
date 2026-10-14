# douyin-image-post-scheduler

一个可安装到 Codex/兼容 Agent 的开源 Skill：从结构化本地素材生成可复现的抖音图文队列，并在用户已登录的 Chrome 中完成批量上传、有效话题选择、音乐设置、定时发布和后台核验。

> 本项目不是抖音官方工具。网页结构可能变化，实际发布前必须检查当前页面和账号状态。

## 解决什么问题

- 批量检查图文素材是否齐全；
- 按第一张图片生成 20 字以内的发布标题；
- 为 1000 字正文限制和 5 个有效话题预留空间；
- 每天多条、指定时间窗口、固定随机种子的可复现排期；
- 避免把纯文本 `#标签` 误判为有效话题；
- 在每条发布前验证图片、标题、正文、话题、音乐和时间；
- 中断后从最后一个成功条目继续，避免重复发布；
- 区分“审核中”和“定时发布中”。

## 仓库结构

```text
skills/douyin-image-post-scheduler/
├── SKILL.md
├── VERSION
├── agents/openai.yaml
├── references/browser-workflow.md
└── scripts/prepare_queue.py
```

仓库不包含抖音账号、Cookie、原始素材、已发布内容、排期结果或录屏。

维护用的文件不属于 Skill：`CLAUDE.md`（给 Agent 的项目约定）、`tools/`（仓库检查、登记反馈）、`tests/`、`docs/`、`.github/`（CI 与反馈处理工作流）。

## 安装

### Codex Skill Installer

在 Codex 中调用 `$skill-installer`，安装下面的 Skill 目录：

```text
https://github.com/chengyi-ai/douyin-image-post-scheduler/tree/main/skills/douyin-image-post-scheduler
```

### 手动安装

```bash
git clone https://github.com/chengyi-ai/douyin-image-post-scheduler.git
mkdir -p ~/.codex/skills
cp -R douyin-image-post-scheduler/skills/douyin-image-post-scheduler ~/.codex/skills/
```

重新打开 Codex 任务后即可使用 `$douyin-image-post-scheduler`。

## 素材格式

每条内容放在以三位编号开头的目录中：

```text
001_内容名称/
├── 01_图片内容/
│   ├── 01_发布标题.jpg
│   ├── 02_第二张图.jpg
│   └── ...
├── 02_文字内容.txt
├── 03_标题内容.txt
└── 04_标签内容.txt
```

默认要求每条 8 张图片和至少 5 个 `#话题`。这些值可以通过脚本参数调整。

## 先生成队列

```bash
python3 skills/douyin-image-post-scheduler/scripts/prepare_queue.py \
  "/absolute/path/to/content-root" \
  --start-date 2026-08-26 \
  --posts-per-day 3 \
  --window-start 09:00 \
  --window-end 22:00 \
  --json-output "/absolute/path/to/douyin-queue.json" \
  --markdown-output "/absolute/path/to/douyin-schedule.md"
```

脚本只读取本地素材并生成计划文件，不会打开浏览器或发布内容。输出中的 `seed` 可用于保持同一批排期完全一致。

## 在 Codex 中使用

```text
使用 $douyin-image-post-scheduler 检查这个素材文件夹，按每天 3 条、北京时间 09:00—22:00 随机排期，并在我已登录的 Chrome 中发布。
```

Skill 的默认发布流程是：

1. 检查准确素材目录和当前抖音账号；
2. 生成 JSON 队列和 Markdown 排期；
3. 上传 8 张图片并填写标题、正文；
4. 把 5 个标签放在独立行，逐个从候选面板激活；
5. 选择收藏夹第一首音乐；
6. 检查公开、允许保存、不跨平台同步和定时时间；
7. 获得整批发布确认后提交；
8. 每条返回内容管理页，批次结束后核验总数和最后一条。

实际对外发布需要用户确认。本 Skill 不保存账号密码、不读取浏览器 Cookie，也不绕过验证码或登录验证。

## 验证

```bash
python3 tools/validate_repo.py
python3 -m unittest discover -s tests -v
python3 skills/douyin-image-post-scheduler/scripts/prepare_queue.py --help
```

测试覆盖队列生成、固定随机种子、图片/标签/标题约束、每天条数和最小时间间隔。`tools/validate_repo.py` 检查 Skill 元数据、文档里的路径、红线声明，以及仓库里没有账号凭据、素材和排期结果。

## 反馈

遇到报错、排期不对或发布流程卡住，直接[提 issue](https://github.com/chengyi-ai/douyin-image-post-scheduler/issues/new/choose)。请不要贴 Cookie、账号密码或未打码的后台截图。

提交后 Agent 会自动读代码评估可行性，在 issue 下回复结论和实现思路；维护者确认后由 Agent 写代码、跑测试、提 PR，合并前一定有人审。涉及绕过验证码、无人确认直接发布这类需求不会被采纳。社媒、群聊里的反馈也能登记进来，整套流程和配置见 [docs/agent-workflow.md](docs/agent-workflow.md)。

## License

[MIT](LICENSE)
