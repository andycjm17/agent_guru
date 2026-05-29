# workflow-distiller · 部署指南

把这套「静默观察你用 AI 干活 → 蒸馏复发工作流 → 四桶分拣 → Map/UI/周报/复盘」的工具
装到你自己的环境。**零配置**：装好飞书 + bytedcli 授权后，解包即用——身份自动探测、
周报文档首次自动创建，不用手填任何 ID 或 URL。

## 前置

1. **Node.js / npm**：用于安装 bytedcli。
2. **bytedcli 已安装并完成飞书授权**：
   ```bash
   npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org
   bytedcli lark auth login
   ```
   这是核心硬前置——工具据此自动拿到你的飞书 `open_id`（DM 收件人）和文档读写权限。
   （`install.sh` 在检测到缺 bytedcli 时会用上面的命令帮你装。）
3. **一个 AI 编码环境（任一即可）**：Claude Code（`~/.claude/projects`）**或** Cursor。
   工具观察的就是你在其中的会话；两者都没有则没有可观察语料。

> **不强绑定 Claude Code**：蒸馏/周报的 LLM 后端自动择优——有 `claude` 用 claude，没有就用
> **字节 AIME**（`bytedcli aime`，随 bytedcli 即得）；也可在 config 配 `mira_endpoint` 走 Mira/ModelHub 网关。
> 工具本身纯 Python stdlib（Python ≥ 3.9），不装任何 pip 包。`lark-cli` 随 bytedcli 就绪。
> `install.sh` 会**自动安装/升级 bytedcli** 到最新；装好后 `python3 -m distiller.doctor` 逐项核验。

## 安装

```bash
tar -xzf workflow-distiller-v1.tar.gz
cd workflow-distiller-v1
./install.sh            # 探测 CLI + 校验飞书授权 + 建目录 + 自检（可选装每周 launchd）
```

装完直接用，**无需编辑任何配置**：

```bash
python3 -m distiller.pipeline        # 观察→蒸馏→出 Workflow Map（首次自动创建 Lark 文档）
python3 -m distiller.server          # 本地 UI：省时 banner + Map + Skills 自主度配置
python3 -m distiller.weekly_update --approve   # 周报：首次自动创建周报文档，之后每周置顶追加
python3 -m distiller.retro --dry-run # 预览每周复盘 DM；去掉 --dry-run 真发到你的飞书
```

自检随时可跑：`python3 -m distiller.doctor`（逐项告知依赖/授权/功能是否就绪）。

## 零配置怎么做到的

| 项 | 零配置机制 |
|---|---|
| 你的飞书 open_id（DM 收件人） | 运行时从 `bytedcli lark auth status` **自动探测** + 缓存（`data/identity.json`） |
| 周报文档 URL | 首次 `weekly_update --approve` **自动创建**「每周 1-on-1-on-1 Update」文档，存 token 复用 |
| Map 文档 | 首次 `pipeline`/`render` **自动创建**，存 token 后续 `update` |
| `claude`/`lark-cli`/`bytedcli` 路径 | `which` **自动探测** |

## 可选自定义（`config.local.json`，全部可省）

只有想覆盖默认时才需要——`./install.sh` 里选「自定义」，或复制 `config.local.example.json`：

| 字段 | 作用 | 不填的默认 |
|---|---|---|
| `tracked_people` | 周报里单列「XX 开发跟进」的人名 | 不输出该节 |
| `ui_port` | 本地 UI 端口 | 8787 |
| `weekly_doc_url` | 钉死到某个已有周报文档 | 首次自动创建 |
| `lark_user_id` | 钉死 DM 收件人 | 自动探测本人 |
| `claude_path`/`lark_cli_path`/`bytedcli_path` | CLI 非标准位置 | `which` 探测 |
| `meeting_state_file` | 并入 meeting-actions 会议语料 | 无则跳过 |

字段也可用环境变量覆盖（`WD_UI_PORT` 等），或 `WD_CONFIG=/path.json` 指定配置文件。

## 每周自动复盘（可选）

`install.sh` 里选 y 装 launchd，或手动：
```bash
sed -e "s#__PROJECT_ROOT__#$(pwd)#g" -e "s#__PYTHON__#$(command -v python3)#g" -e "s#__HOME__#$HOME#g" \
    com.workflow-distiller.plist.template > ~/Library/LaunchAgents/com.workflow-distiller.plist
launchctl load ~/Library/LaunchAgents/com.workflow-distiller.plist   # 每周一 09:00
```

## 隐私与边界

- 全部在**本机**运行；UI 绑 `127.0.0.1`，不对外。
- `config.local.json`、`data/`（含文档 token、`identity.json`）默认**不入库、不进安装包**。
- 省时数字一律为**诚实估算**（标 `~`），含负值，不做虚荣指标。
- Agent 观察不到的（走廊对话、会上拍板）= 不可替代的人类残差，工具不碰。
- 只**读** `~/.claude/projects`，不改你的会话历史。

## 重新打包分发

```bash
./package.sh v1      # 生成 dist/workflow-distiller-v1.tar.gz（自动剔除个人配置/token/数据）
```
