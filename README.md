<!-- [English](README.en.md) | 中文 -->

# workflow-distiller

workflow-distiller 观察 AI 协作会话，将反复出现的工作流蒸馏为四类——**消除 / 自动化 / Skill / 人**——并直接生成可运行的 Skill 与自动化，让精力向不可替代的人类判断迁移。

- **可插拔，不绑定单一平台**
  - 观察源：Claude Code / Cursor / Codex（任选其一或多个，同时作为 Skill 的应用目标）
  - 通知渠道：飞书 / 本地文件 / Slack
  - LLM 后端：Claude / 字节 AIME / Mira 网关
- **零配置启动**：平台与身份自动探测，文档首次自动创建，无个人信息硬编码。
- **纯标准库**：Python ≥ 3.9，不依赖任何 pip 包。

部署说明见 [SETUP.md](SETUP.md)。

## 快速开始

```bash
# 1. （可选）选择平台：观察源 / 通知渠道 / 默认应用目标
python3 -m distiller.setup               # 或在 Dashboard 的「⚙ 设置」中配置

# 2. 运行主流程：观察 → 蒸馏 → 交付到启用的渠道
python3 -m distiller.pipeline            # 加 --no-lark 仅生成结果、不对外交付

# 3. 打开本地 Dashboard
python3 -m distiller.server              # http://127.0.0.1:8787

# 4. 生成本周周报草稿
python3 -m distiller.weekly_update       # 加 --approve 推送到周报文档

# 5. 每周复盘
python3 -m distiller.retro --dry-run     # 去掉 --dry-run 后正式发送
```

## 工作原理

工具将每条复发工作流的每一步归入四类，并随自主度逐级推进自动化：

| 类别 | 判据 | 产物 |
|---|---|---|
| 消除 eliminate | 无人使用 / 历史包袱 | 停用建议 |
| 自动化 automate | 确定性、规则化、同输入同输出 | 脚本 / launchd 定时任务 |
| Skill skill | 需判断、但可蒸馏复用 | `SKILL.md` |
| 人 human | 人际 / 信任 / 问责 / 拍板 | 显式标注，保留给人 |

**自主度梯度**（在 Dashboard 中逐项配置）：建议 → 待批草稿 → 自动化（通知）→ 全自动。

主流程分三段：**观察**（采集会话摘要）→ **蒸馏**（LLM 聚类工作流并分类）→ **交付**（生成 Workflow Map、Skill 与周报，发送至启用的渠道）。

## Dashboard

`python3 -m distiller.server` 打开 `http://127.0.0.1:8787`：

- **使用概览**：基于会话记录的实测计数（Skill 调用次数、自动化运行次数）。省时为明确标注的估算，仅供参考。
- **Workflow Map**：点击任意行展开步骤分类与建议；「蒸馏成 Skill」可将该工作流生成为 SKILL.md 草稿。
- **Skills**：点击任意行编辑 SKILL.md 与自主度；「应用到生产」在写回目标平台前自动备份原版。
- **⚙ 设置**：配置观察源、通知渠道、默认应用目标与 Slack Webhook，保存后即时生效。

## 组件

| 模块 | 职责 |
|---|---|
| `config.py` | 共享底座：路径、常量、CLI 解析、LLM 抽象（Claude/AIME/Mira）、配置读写与备份 |
| `agents/` | 可插拔 Agent 平台（`claude_code` / `cursor` / `codex`）：观察源，同时作为 Skill 应用目标 |
| `sinks/` | 可插拔通知渠道（`feishu` / `local` / `slack`）：`broadcast_dm` / `broadcast_report` 分发 |
| `observe.py` | 遍历启用的观察源，采集会话摘要至 `digests.json`（仅摘要，含来源统计） |
| `distill.py` | 将摘要交由 LLM 聚类为复发工作流并分类，输出 `map.json` |
| `render.py` | 将 `map.json` 渲染为 DocxXML（飞书）与 Markdown（本地/Slack），分发至启用渠道 |
| `usage.py` | 从会话记录统计 Skill 调用次数（实测） |
| `savings.py` | 省时账本：记录真实自动化运行，输出净值与概览 |
| `server.py` + `ui/` | 本地 Dashboard：使用概览、Workflow Map、Skills 编辑器、平台设置 |
| `setup.py` | 平台选择向导：探测可用平台，写回 `config.local.json` |
| `weekly_update.py` | 汇总本周信号，生成结构化周报，`--approve` 后推送 |
| `retro.py` | 重跑观察与蒸馏，对比新增工作流，发送每周复盘 |
| `doctor.py` | 环境自检：逐项核验依赖、平台、渠道，区分阻断项与降级项 |
| `pipeline.py` | 主流程编排：观察 → 蒸馏 → 交付 |

## 定时复盘（可选）

`install.sh` 提供一键安装；或手动生成 launchd 任务（占位符自动填充）：

```bash
sed -e "s#__PROJECT_ROOT__#$(pwd)#g" -e "s#__PYTHON__#$(command -v python3)#g" -e "s#__HOME__#$HOME#g" \
    com.workflow-distiller.plist.template > ~/Library/LaunchAgents/com.workflow-distiller.plist
launchctl load ~/Library/LaunchAgents/com.workflow-distiller.plist   # 每周一 09:00 触发复盘
```

## 设计原则

- **只对可观察的部分下手**。Agent 观察不到的环节（走廊对话、会上拍板）即不可替代的人类判断，工具不介入。
- **诚实计量**。Dashboard 优先展示实测计数；省时为反事实估算，统一标注 `~` 并可为负，不作为虚荣指标。
- **只读会话历史**，不修改任何已有会话。
