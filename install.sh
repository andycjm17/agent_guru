#!/usr/bin/env bash
# workflow-distiller 安装/配置（零配置优先，可重复运行）
#   ./install.sh        建目录 + 自检；身份自动探测、周报文档自动创建，无需手填
#   ./install.sh -y     全自动、无任何交互（CI/远程）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
NONINTERACTIVE="${1:-}"
say() { printf '%s\n' "$*"; }

say "==================================================="
say " workflow-distiller 安装  ($HERE)"
say "==================================================="

# ---- 1) Python ≥ 3.9 ----
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { say "✗ 未找到 python3（需 ≥ 3.9）"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)' \
  || { say "✗ python3 版本过低（需 ≥ 3.9）：$("$PY" -V)"; exit 1; }
say "✓ $("$PY" -V)"

BYTEDCLI_INSTALL="npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org"

# ---- 2) 运行时工具链 + 外部 CLI ----
detect() { command -v "$1" 2>/dev/null || true; }
NODE_P="$(detect node)"; NPM_P="$(detect npm)"
say "  node=${NODE_P:-未找到}  npm=${NPM_P:-未找到}"
CLAUDE_P="$(detect claude)"; BYTED_P="$(detect bytedcli)"; LARK_P="$(detect lark-cli)"

# bytedcli：缺则自动安装、有则自动升级到最新（前置依赖：飞书 + Aime 后端）
if [ -z "$NPM_P" ]; then
  [ -z "$BYTED_P" ] && say "  ✗ 未找到 npm，无法安装 bytedcli。请先装 Node.js（含 npm）后重跑。"
else
  if [ -z "$BYTED_P" ]; then
    say "  未找到 bytedcli → 自动安装：$BYTEDCLI_INSTALL"
    npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org || say "  ⚠ 安装失败，请手动执行上面命令"
    BYTED_P="$(detect bytedcli)"; LARK_P="$(detect lark-cli)"
  else
    UP=0
    if [ "$NONINTERACTIVE" = "-y" ]; then UP=1
    elif [ -t 0 ]; then read -r -p "  bytedcli 已装（$("$BYTED_P" --version 2>/dev/null||echo ?)），升级到最新? [y/N] " a; [ "${a:-N}" = "y" ] || [ "${a:-N}" = "Y" ] && UP=1; fi
    if [ "$UP" = 1 ]; then
      say "  → 升级：$BYTEDCLI_INSTALL"
      npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org || say "  ⚠ 升级失败"
      BYTED_P="$(detect bytedcli)"; LARK_P="$(detect lark-cli)"
    fi
  fi
fi
say "  claude=${CLAUDE_P:-未找到}  bytedcli=${BYTED_P:-未找到}  lark-cli=${LARK_P:-未找到}"
# claude 可选：缺了用 Aime(bytedcli) 作为 LLM 后端
if [ -z "$CLAUDE_P" ]; then
  if [ -n "$BYTED_P" ]; then say "  · 未装 claude → 自动用字节 Aime(bytedcli) 作为蒸馏/周报后端，无需 Claude Code"
  else say "  ⚠ 既无 claude 也无 bytedcli → 无 LLM 后端；至少装一个"; fi
fi

# ---- 3) 验证飞书授权（本工具的核心前置）----
if [ -n "$BYTED_P" ]; then
  if "$BYTED_P" -j lark auth status 2>/dev/null | grep -q '"openId"'; then
    WHO="$("$BYTED_P" -j lark auth status 2>/dev/null | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print(((d.get("identities") or {}).get("user") or {}).get("userName",""))' 2>/dev/null || true)"
    say "  ✓ 飞书已授权：${WHO:-(已登录)}  → open_id 将自动探测，无需手填"
  else
    say "  ⚠ bytedcli 尚未完成飞书授权 → 先跑：bytedcli lark auth login（之后 DM/周报即自动可用）"
  fi
fi

# ---- 4) 目录 ----
mkdir -p data/state logs
say "  ✓ 数据/日志目录就绪"

# ---- 5) 可选自定义（默认跳过；零配置已可跑）----
if [ "$NONINTERACTIVE" != "-y" ] && [ -t 0 ] && [ ! -f config.local.json ]; then
  read -r -p "需要自定义吗(单列跟进人/端口/指定已有周报文档)? 默认否 [y/N] " a
  if [ "${a:-N}" = "y" ] || [ "${a:-N}" = "Y" ]; then
    read -r -p "  单列跟进的人名 (逗号分隔，可空): " PPL
    read -r -p "  UI 端口 [8787]: " PORT; PORT="${PORT:-8787}"
    read -r -p "  已有周报文档 URL (可空，留空则首次自动创建): " WURL
    "$PY" - "${PPL:-}" "$PORT" "${WURL:-}" <<'PYEOF'
import json, sys
ppl, port, wurl = (sys.argv[1:4] + [""]*3)[:3]
cfg = {}
people = [x.strip() for x in ppl.split(",") if x.strip()]
if people: cfg["tracked_people"] = people
try: cfg["ui_port"] = int(port)
except ValueError: cfg["ui_port"] = 8787
if wurl.strip(): cfg["weekly_doc_url"] = wurl.strip()
open("config.local.json","w",encoding="utf-8").write(json.dumps(cfg,ensure_ascii=False,indent=2))
print("  ✓ 已写 config.local.json")
PYEOF
  fi
fi

# ---- 6) 自检 ----
say ""
"$PY" -m distiller.doctor || true

# ---- 7) 可选 launchd（每周复盘）----
if [ "$(uname)" = "Darwin" ] && [ "$NONINTERACTIVE" != "-y" ] && [ -t 0 ]; then
  say ""
  read -r -p "安装『每周一 09:00 自动复盘并发飞书』? [y/N] " a
  if [ "${a:-N}" = "y" ] || [ "${a:-N}" = "Y" ]; then
    PLIST="$HOME/Library/LaunchAgents/com.workflow-distiller.plist"
    sed -e "s#__PROJECT_ROOT__#$HERE#g" -e "s#__PYTHON__#$PY#g" -e "s#__HOME__#$HOME#g" \
        com.workflow-distiller.plist.template > "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load "$PLIST" && say "  ✓ 已加载（卸载: launchctl unload \"$PLIST\"）" \
      || say "  ⚠ load 失败，可手动: launchctl load \"$PLIST\""
  fi
fi

say ""
say "完成 ✓  直接开始用："
say "  $PY -m distiller.pipeline      # 观察→蒸馏→出 Map（首次推 Lark 文档）"
say "  $PY -m distiller.server        # 本地 UI"
say "  $PY -m distiller.retro --dry-run   # 预览每周复盘 DM（去掉 --dry-run 真发，open_id 自动探测）"
