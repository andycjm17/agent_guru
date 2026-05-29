# workflow-distiller · v1

静默旁观你用 AI 干活，把复发工作流持续蒸馏进四个桶 —— **消除 / 自动化 / Skill / 人**，
并把 Skill 和自动化真正生成出来跑起来，让时间向不可替代的人类部分迁移。

> 零配置：装好飞书 + bytedcli 授权即用——用户名/open_id 自动探测、文档自动创建，无人名硬编码。
> 部署见 [SETUP.md](SETUP.md)。

## 快速上手

```bash
cd <你解包/克隆的目录>

# 串行整体流程（观察 → 蒸馏 → 推 Lark Map 文档）
python3 -m distiller.pipeline            # --no-lark 可只跑认知不推文档

# 本地 UI：省时 banner + Workflow Map + Skills 自主度配置
python3 -m distiller.server              # → http://127.0.0.1:8787

# 本周周报草稿（§3.9 / weekly 约定；draft-for-approval）
python3 -m distiller.weekly_update       # --approve 才推送到 live 周报文档

# 每周复盘 + 飞书 DM 速递
python3 -m distiller.retro --dry-run     # 去掉 --dry-run 真发；--skip-distill 省 claude
```

## 组件

| 模块 | 桶/角色 | 职责 |
|---|---|---|
| `config.py` | 底座 | 路径/常量/CLI 绝对路径；`run` `log` `claude_p` `lark_dm` `extract_json` JSON IO |
| `observe.py` | 观察 | 扫 `~/.claude/projects/**/*.jsonl` + 会议 → 紧凑 session 摘要 `digests.json`（不搬全文） |
| `distill.py` | 蒸馏 | digests → `claude -p` 聚类复发工作流 + 四桶分拣 + next_action → `map.json` |
| `render.py` | 交付① | `map.json` → DocxXML（结论先行/表格/无 emoji）→ lark-cli create/update（token 存 `lark_doc.json`） |
| `savings.py` | 价值③ | 省时账本 `savings_ledger.jsonl`，净值=省−开销，punchline（**含负值**） |
| `server.py`+`ui/` | UI | http.server 单页：banner + Map 表 + Skills 自主度下拉（回写 `skills_config.json`） |
| `weekly_update.py` | 闭环② | 本周信号 → claude 出结构化 JSON → Python 确定性渲染 §3.9 周报草稿 → `--approve` 推 Lark |
| `retro.py` | 闭环 | 重跑 observe+distill，diff 新工作流，算省时，bytedcli DM 速递（幂等键=`retro-<week>`） |
| `pipeline.py` | 编排 | observe→distill→render 串行入口 |

## 四桶

| 桶 | 判据 | 产物 |
|---|---|---|
| 消除 eliminate | 没人看 / 历史包袱 | "停掉它"建议 |
| 自动化 automate | 确定性、规则化、同输入同输出 | launchd plist / 脚本 |
| Skill skill | 需判断但可蒸馏复用 | `SKILL.md` |
| 人 human | 人际 / 信任 / 问责 / 拍板 | 显式命名、留给人 |

桶向下流动（人→Skill→自动化）由 UI 自主度开关控制：建议 → 待批草稿 → 自动+通知 → 全自动。

## 定时（每周复盘）

`./install.sh` 里选 y 自动安装；或手动用模板生成（路径自动填充）：

```bash
sed -e "s#__PROJECT_ROOT__#$(pwd)#g" -e "s#__PYTHON__#$(command -v python3)#g" -e "s#__HOME__#$HOME#g" \
    com.workflow-distiller.plist.template > ~/Library/LaunchAgents/com.workflow-distiller.plist
launchctl load ~/Library/LaunchAgents/com.workflow-distiller.plist   # 每周一 09:00 触发 retro
```

## 设计自洽点

Agent 观察不到的残差 ≈ 不可替代的人类残差（走廊对话、会上拍板都不经过 AI）。工具只对看得见的下手。
省时一律诚实估算（标 `~`）、显示净值与负值，避免变虚荣指标。
