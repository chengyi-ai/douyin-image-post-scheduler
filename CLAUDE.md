# CLAUDE.md

本仓库是开源 Agent Skill「douyin-image-post-scheduler」：从结构化本地素材生成可复现的抖音图文发布队列，并在用户已登录的 Chrome 中完成批量上传、有效话题选择、音乐设置、定时发布和后台核验。Skill 本体在 `skills/douyin-image-post-scheduler/`，用户把这个目录复制到 Agent 的 Skills 目录使用。本项目不是抖音官方工具。

## 目录

- `skills/douyin-image-post-scheduler/`：Skill 本体。
  - `SKILL.md`：Agent 使用说明（素材约定、默认配置、执行原则、停止条件）。
  - `references/browser-workflow.md`：Chrome 里上传、填写、激活话题、选音乐、定时和核验的页面操作。
  - `scripts/prepare_queue.py`：只读素材、生成 JSON 队列和 Markdown 排期，不打开浏览器、不上传、不发布。
  - `agents/openai.yaml`：Codex 的展示名和默认提示；`VERSION`：Skill 版本号。
- `tests/`：`unittest` 测试，在临时目录里造素材。
- `tools/`：维护用脚本（`validate_repo.py` 仓库检查、`submit_feedback.py` 登记反馈），不属于 Skill 流程。
- `.github/`：CI（`ci.yml`）与 Agent 反馈处理工作流，见 `docs/agent-workflow.md`。

## 不可违背的原则

- 实际对外发布前必须得到用户确认（整批确认即可）；发布前断言任一项失败都不点发布。
- 不保存账号密码、不读取浏览器 Cookie、不新开或导出登录态；只复用用户已经登录的 Chrome。
- 不绕过验证码、登录验证或平台风控与频率限制；遇到登录失效、验证码、账号不匹配、平台拒绝排期时停下并报告。
- `prepare_queue.py` 只读素材、只写计划文件，不引入浏览器自动化、网络请求或子进程（`tools/validate_repo.py` 会检查）。
- 不改写用户原文：正文超长只在完整句子处截断；话题必须是平台识别的有效话题，不静默换成无关热门话题。
- 未经用户明确授权，不删除、重发或修改已经提交的内容。
- 仓库里不放账号、Cookie、原始素材、已发布内容、排期结果或录屏。

代码改动不能削弱 `SKILL.md`、`references/browser-workflow.md` 里的发布确认、发布前断言和停止条件，也不能放宽 `tools/validate_repo.py` 对这些红线的检查。

## 开发约定

- Python 3.10+，只用标准库，不引入第三方依赖。
- 提交前必须通过：

  ```bash
  python tools/validate_repo.py
  python -m unittest discover -s tests
  python skills/douyin-image-post-scheduler/scripts/prepare_queue.py --help
  ```

- 行为改动配测试；测试在临时目录里造素材，不依赖真实素材、浏览器、网络或抖音账号。
- 不改没被要求的默认值：发布设置（公开、允许保存、不同步其他平台、收藏第一首音乐）、默认排期（每天 3 条、09:00—22:00、最小间隔 90 分钟、Asia/Shanghai）、标题 20 字 / 正文 1000 字 / 5 个话题上限。
- 用户可见变化同步 `SKILL.md`、`README.md`；页面操作变化同步 `references/browser-workflow.md`，并说明需要在真实页面上验证哪些步骤（CI 里没有浏览器）。
- `VERSION` 由维护者在发版时修改。
- 提交信息使用 `fix:` / `feat:` / `docs:` / `test:` / `ci:` 前缀，简体中文描述。
