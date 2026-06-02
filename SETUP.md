<!-- [English](SETUP.en.md) | 中文 -->

# 部署指南

将 workflow-distiller 部署到本地环境。完成飞书 + bytedcli 授权后即可使用——身份自动探测，周报文档首次自动创建，无需手动填写任何 ID 或 URL。

## 前置条件

1. **Node.js / npm**：用于安装 bytedcli。
2. **bytedcli（已完成飞书授权）**：

   ```bash
   npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org
   bytedcli lark auth login
   ```

   工具据此自动获取飞书 `open_id`（DM 收件人）与文档读写权限。若检测到缺失，`install.sh` 会自动安装。

3. **至少一个 AI 编码环境**：Claude Code（`~/.claude/projects`）、Cursor 或 Codex CLI（`~/.codex/sessions`）。工具观察其中的会话作为输入；三者皆无则没有可观察的数据。

> **可插拔说明**
> - 观察源：Claude Code / Cursor / Codex，任选其一或多个，自动探测。观察源同时作为 Skill 的应用目标。
> - 通知渠道：飞书 / 本地文件（`data/out/`，零依赖）/ Slack（填写 Webhook 后启用）。
> - LLM 后端：优先使用本地 `claude`；不可用时自动切换至字节 AIME（随 bytedcli 提供），或配置 `mira_endpoint` 走 Mira / ModelHub 网关。
>
> 平台选择可通过 `python3 -m distiller.setup` 向导或 Dashboard 的「⚙ 设置」完成，二者写入同一份配置。工具仅依赖 Python 标准库（≥ 3.9），不安装任何 pip 包；`lark-cli` 随 bytedcli 提供。

## 安装

```bash
tar -xzf workflow-distiller-v1.tar.gz
cd workflow-distiller-v1
./install.sh            # 探测 CLI、校验飞书授权、创建目录、运行自检（可选安装定时复盘）
```

安装后无需编辑任何配置即可使用（默认自动探测平台）：

```bash
python3 -m distiller.setup           # 可选：平台选择向导
python3 -m distiller.pipeline        # 观察 → 蒸馏 → 生成 Workflow Map 并交付
python3 -m distiller.server          # 本地 Dashboard
python3 -m distiller.weekly_update --approve   # 周报：飞书渠道置顶追加，其余渠道写入本地 / Slack
python3 -m distiller.retro --dry-run # 预览每周复盘；去掉 --dry-run 后正式发送
```

随时可运行环境自检：`python3 -m distiller.doctor`；加 `--fix` 可在检测后顺手装上能自动化的缺失项（建目录、`npm` 装 bytedcli），`--fix -y` 跳过确认（非交互/CI）。飞书 SSO 登录为交互式，无法自动化，仅提示命令。

## Dashboard 操作

`python3 -m distiller.server` 打开 `http://127.0.0.1:8787`：

- **Workflow Map**：点击任意行展开步骤分类与建议。「蒸馏成 Skill」将该工作流生成为 SKILL.md 草稿，编辑后即可应用。
- **Skills**：点击任意行编辑 SKILL.md 与自主度。「应用到生产」会先将原版备份至 `data/backups/`，再原子写回目标平台的对应路径：
  - Claude Code：`~/.claude/skills/<name>/SKILL.md`
  - Cursor：`.cursor/rules/<name>.mdc`
  - Codex：`~/.codex/prompts/<name>.md`
- **⚙ 设置**：配置观察源、通知渠道、默认应用目标与 Slack Webhook，保存后即时生效。

## 零配置机制

| 项目 | 机制 |
|---|---|
| 飞书 open_id（DM 收件人） | 运行时从 `bytedcli lark auth status` 自动探测并缓存至 `data/identity.json` |
| 周报文档 | 首次 `weekly_update --approve` 自动创建并保存 token，后续复用 |
| Map 文档 | 首次 `pipeline` / `render` 自动创建并保存 token，后续更新 |
| `claude` / `lark-cli` / `bytedcli` 路径 | 通过 `which` 自动探测 |

## 可选配置

所有字段均可省略。如需覆盖默认行为，复制 `config.local.example.json` 为 `config.local.json` 并填写：

| 字段 | 说明 | 默认 |
|---|---|---|
| `sources` | 启用的观察源（`claude_code` / `cursor` / `codex`） | 自动探测所有可用平台 |
| `sinks` | 启用的通知渠道（`feishu` / `local` / `slack`） | 飞书可用则用飞书，否则本地 |
| `skill_target` | 默认应用目标平台 | 首个可写的启用平台 |
| `slack_webhook` | Slack Incoming Webhook URL | 未配置则跳过 Slack |
| `cursor_rules_dir` | Cursor `.mdc` 应用目录 | `~/.cursor/rules` |
| `tracked_people` | 周报中单列开发跟进的人员 | 不输出该节 |
| `ui_port` | Dashboard 端口 | 8787 |
| `weekly_doc_url` | 指定已有周报文档 | 首次自动创建 |
| `lark_user_id` | 指定 DM 收件人 | 自动探测当前用户 |
| `claude_path` / `lark_cli_path` / `bytedcli_path` | CLI 非标准安装路径 | `which` 探测 |
| `meeting_state_file` | 并入 meeting-actions 会议数据 | 不启用 |

字段也可通过环境变量覆盖（如 `WD_UI_PORT`），或用 `WD_CONFIG=/path.json` 指定配置文件位置。

## 定时复盘（可选）

通过 `install.sh` 安装，或手动生成 launchd 任务：

```bash
sed -e "s#__PROJECT_ROOT__#$(pwd)#g" -e "s#__PYTHON__#$(command -v python3)#g" -e "s#__HOME__#$HOME#g" \
    com.workflow-distiller.plist.template > ~/Library/LaunchAgents/com.workflow-distiller.plist
launchctl load ~/Library/LaunchAgents/com.workflow-distiller.plist   # 每周一 09:00
```

## 隐私与边界

- 全部在本机运行；Dashboard 绑定 `127.0.0.1`，不对外暴露。
- `config.local.json` 与 `data/`（含文档 token、`identity.json`）默认不纳入版本库、不进入安装包。
- Dashboard 优先展示实测计数；省时为估算（标注 `~`，可为负），不作为虚荣指标。
- 仅读取会话历史，不修改任何已有会话。

## 重新打包

```bash
./package.sh v1      # 生成 dist/workflow-distiller-v1.tar.gz（自动剔除个人配置、token 与数据）
```
