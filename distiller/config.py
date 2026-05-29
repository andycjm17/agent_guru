#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
workflow-distiller · 共享底座

集中所有路径、常量、外部 CLI 绝对路径，以及被多个模块复用的小工具
（log / run / claude_p / JSON IO）。其余模块一律从这里导入，不各自硬编码。

设计照搬 ~/.meeting-actions/meeting_actions.py 的范式：
  - run() 统一子进程封装
  - CLI 用绝对路径（PATH 在 launchd 下不可靠）
  - bytedcli 一律 -j 取 JSON（绕开 0.67.0 的 --format 注入 bug）
  - lark-cli docs +create/+update 直接调（绕开 bytedcli 包装层 60s 超时）
"""
import json
import os
import re
import shutil
import subprocess
import time
import datetime as dt
import pathlib

# ---------- 路径 ----------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
LOG_DIR = PROJECT_ROOT / "logs"
UI_DIR = PROJECT_ROOT / "ui"

DIGESTS_FILE = DATA_DIR / "digests.json"
MAP_FILE = DATA_DIR / "map.json"
SAVINGS_LEDGER = DATA_DIR / "savings_ledger.jsonl"
SKILLS_CONFIG = DATA_DIR / "skills_config.json"
LARK_DOC_FILE = DATA_DIR / "lark_doc.json"          # 存 Map 文档 token，供 update 复用
WEEKLY_DOC_FILE = DATA_DIR / "weekly_doc.json"      # 存周报文档 token（首次自动创建后写入）
IDENTITY_CACHE = DATA_DIR / "identity.json"         # 缓存自动探测到的本人 open_id
PROCESSED_FILE = STATE_DIR / "processed.json"       # retro 去重

HOME = pathlib.Path.home()

# ---------- 本地配置层（可移植部署的关键：所有个人/环境相关项都从这里来）----------
# 查找顺序：环境变量 $WD_CONFIG 指定的文件 → 项目根 config.local.json。该文件每人一份、不入库。
def _load_local_config() -> dict:
    candidates = []
    env_path = os.environ.get("WD_CONFIG")
    if env_path:
        candidates.append(pathlib.Path(env_path))
    candidates.append(PROJECT_ROOT / "config.local.json")
    for p in candidates:
        try:
            if p.exists():
                obj = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(obj, dict):
                    return obj
        except Exception:
            pass
    return {}


_CFG = _load_local_config()


def _cfg(key, default=None):
    """配置取值优先级：config.local.json[key] → 环境变量 WD_<KEY> → default。"""
    if key in _CFG and _CFG[key] not in (None, ""):
        return _CFG[key]
    env = os.environ.get("WD_" + key.upper())
    if env not in (None, ""):
        return env
    return default


def _resolve_cli(name: str, cfg_key: str, fallback: str) -> str:
    """解析 CLI 路径：config 指定 → PATH 中 which 自动探测 → 候选 fallback → 裸名(靠运行时 PATH)。"""
    v = _cfg(cfg_key)
    if v:
        return v
    found = shutil.which(name)
    if found:
        return found
    if fallback and pathlib.Path(fallback).exists():
        return fallback
    return name


# ---------- 外部语料（可被 config 覆盖；默认相对 HOME，天然可移植）----------
CLAUDE_PROJECTS = pathlib.Path(_cfg("claude_projects_dir", HOME / ".claude" / "projects"))
CLAUDE_SKILLS = pathlib.Path(_cfg("claude_skills_dir", HOME / ".claude" / "skills"))
MEETING_STATE = pathlib.Path(_cfg("meeting_state_file", HOME / ".meeting-actions" / "state" / "processed.json"))
MEETING_TX_DIR = pathlib.Path(_cfg("meeting_tx_dir", HOME / ".meeting-actions" / "transcripts"))

# ---------- 身份 / CLI / 部署项 ----------
LARK_USER_ID = _cfg("lark_user_id", "")     # 飞书 DM 收件人 open_id；空 = 禁用 DM（lark_dm 会跳过）
SELF_OPEN_ID = LARK_USER_ID                 # 向后兼容别名
BYTEDCLI = _resolve_cli("bytedcli", "bytedcli_path", "/opt/homebrew/bin/bytedcli")
LARK_CLI = _resolve_cli("lark-cli", "lark_cli_path", "/opt/homebrew/bin/lark-cli")
CLAUDE = _resolve_cli("claude", "claude_path", str(HOME / ".local" / "bin" / "claude"))

WEEKLY_DOC_URL = _cfg("weekly_doc_url", "")  # 周报文档 URL；空 = weekly --approve 禁用
TRACKED_PEOPLE = _cfg("tracked_people", [])  # 单列跟进的人名；空 = 不输出该节


def _int_cfg(key, default):
    """整数型配置安全解析：脏值（非数字 env / config）降级为 default，
    绝不让一处错配在 import 期抛 ValueError 拖垮整个包（doctor 都跑不起来）。"""
    try:
        return int(_cfg(key, default))
    except (TypeError, ValueError):
        return default


UI_PORT = _int_cfg("ui_port", 8787)

# 四桶
BUCKETS = ["eliminate", "automate", "skill", "human"]
BUCKET_ZH = {
    "eliminate": "消除",
    "automate": "自动化",
    "skill": "Skill",
    "human": "人",
}
# UI 自主度梯度（桶向下流动的控制档位）
AUTONOMY_LEVELS = ["suggest", "draft", "auto_notify", "full_auto"]
AUTONOMY_ZH = {
    "suggest": "仅建议",
    "draft": "待批草稿",
    "auto_notify": "自动+通知",
    "full_auto": "全自动",
}

# ---------- 小工具 ----------
def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_ts(ts) -> "dt.datetime | None":
    """解析 ISO 时间戳（兼容尾部 Z）。无法解析返回 None；naive 时间补 UTC，
    保证可与 now_utc() 等 tz-aware 时间安全比较、也避免同会话内 naive/aware 混比崩溃。"""
    if not ts:
        return None
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def as_num(x, default=0.0) -> float:
    """把『本应是数字』的字段安全转 float（LLM 可能返回 "15min"/"high"/"~5"，账本可手写脏值）。
    转不动就降级为 default，避免裸 float()/int()/sum() 让整链崩。"""
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def log(msg: str, logfile: str = "run.log") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with (LOG_DIR / logfile).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout=None, **kw) -> subprocess.CompletedProcess:
    """统一子进程封装：捕获 stdout/stderr、text 模式。"""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


def load_json(path: pathlib.Path, default=None):
    p = pathlib.Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path: pathlib.Path, obj) -> None:
    """原子写：先写同目录 .tmp 再 replace，避免写一半被中断留下损坏 JSON。"""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)   # 同目录、同文件系统 → 原子替换


def append_jsonl(path: pathlib.Path, obj) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read_jsonl(path: pathlib.Path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


# ---------- claude -p ----------
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str):
    """从 claude -p 的自由文本里抠出 JSON 对象/数组。
    依次尝试：整体解析 → 去 ```fence``` → 抓首个 {…} / […] 平衡括号。
    """
    if not text:
        return None
    text = text.strip()
    # 1) 直接
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) 代码块
    m = _JSON_FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 3) 平衡括号扫描（取最外层 {} 或 []）
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    chunk = text[start:i + 1]
                    try:
                        return json.loads(chunk)
                    except Exception:
                        break
    return None


# ============ LLM 后端抽象（解绑 Claude Code：claude / aime / mira 任一可用即可跑）============
LLM_PROVIDER = _cfg("llm_provider", "auto")   # auto | claude | aime | mira


def _cli_exists(path: str, name: str) -> bool:
    return bool(shutil.which(name)) or pathlib.Path(path).exists()


def llm_providers_available() -> list:
    """当前环境可用的 LLM 后端。"""
    avail = []
    if _cli_exists(CLAUDE, "claude"):
        avail.append("claude")
    if _cli_exists(BYTEDCLI, "bytedcli"):
        avail.append("aime")          # 字节内置 AIME，随 bytedcli 提供
    if _cfg("mira_endpoint"):
        avail.append("mira")          # 配置驱动的 HTTP 网关（如 Mira/ModelHub）
    return avail


def active_provider() -> str:
    if LLM_PROVIDER and LLM_PROVIDER != "auto":
        return LLM_PROVIDER
    avail = llm_providers_available()
    for p in ("claude", "aime", "mira"):   # 偏好：本地 claude → 字节 aime → 网关 mira
        if p in avail:
            return p
    return "claude"


def _llm_claude(prompt: str, timeout: int):
    r = run([CLAUDE, "-p", prompt], timeout=timeout)
    return (r.stdout or "").strip(), (r.stderr or "")


def _llm_aime(prompt: str, timeout: int):
    """字节内置 AIME：bytedcli aime chat 非流式，回复在 data.response。"""
    r = run([BYTEDCLI, "-j", "aime", "chat", "--auto-session", "--no-stream",
             "--message", prompt], timeout=timeout)
    try:
        d = json.loads(r.stdout or "{}")
    except Exception as e:
        return "", f"aime 解析失败: {e!r} {(r.stdout or '')[:150]}"
    if isinstance(d, dict) and d.get("status") == "success":
        return ((d.get("data") or {}).get("response") or "").strip(), ""
    return "", f"aime 返回非成功: {str(d)[:200]}"


def _llm_mira(prompt: str, timeout: int):
    """配置驱动的 HTTP 网关（Mira / ModelHub 等，OpenAI 兼容 chat 形态）。
    需在 config.local.json 配 mira_endpoint（必）、mira_token / mira_model（可选）。"""
    endpoint = _cfg("mira_endpoint")
    if not endpoint:
        return "", "未配置 mira_endpoint"
    import urllib.request
    token = _cfg("mira_token", "")
    model = _cfg("mira_model", "") or "default"
    body = json.dumps({"model": model, "stream": False,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return "", f"mira http 失败: {e!r}"
    txt = (((d.get("choices") or [{}])[0].get("message") or {}).get("content")
           or d.get("response") or ((d.get("data") or {}).get("response")) or "")
    return (txt or "").strip(), ("" if txt else f"mira 无内容: {str(d)[:150]}")


_LLM_FUNCS = {"claude": _llm_claude, "aime": _llm_aime, "mira": _llm_mira}


def llm(prompt: str, timeout: int = 300, expect_json: bool = False,
        retries: int = 2, provider: str = None):
    """统一 LLM 调用（自动择优 claude/aime/mira）。expect_json 时返回解析对象，否则文本；失败 None。
    对瞬时失败（空输出 / socket 错误 / JSON 解析失败）重试 retries 次，指数退避。"""
    prov = provider or active_provider()
    fn = _LLM_FUNCS.get(prov, _llm_claude)
    last = None
    for attempt in range(retries + 1):
        try:
            out, err = fn(prompt, timeout)
        except Exception as e:
            out, err = "", f"run 异常: {e!r}"
        out = (out or "").strip()
        low = out.lower()
        looks_json = out[:1] in ("{", "[")
        transient = (not out) or ("socket connection was closed" in low) or \
                    ("api error" in low and len(out) < 400 and not looks_json) or \
                    (bool(err) and not out)
        if transient:
            last = f"[{prov}] 瞬时失败: {(out or err)[:200]}"
            log(f"llm 第 {attempt+1}/{retries+1} 次 {last}")
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            return None
        if expect_json:
            obj = extract_json(out)
            if obj is None:
                last = f"[{prov}] JSON 解析失败; head={out[:200]}"
                log(f"llm 第 {attempt+1}/{retries+1} 次 {last}")
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                return None
            return obj
        return out
    log(f"llm 最终失败: {last}")
    return None


# 向后兼容：旧代码用 claude_p()，现转调 llm()（后端按 active_provider 自动选）
def claude_p(prompt: str, timeout: int = 300, expect_json: bool = False, retries: int = 2):
    return llm(prompt, timeout=timeout, expect_json=expect_json, retries=retries)


def resolve_lark_user_id() -> str:
    """零配置解析本人 open_id：config 显式值 → 缓存 → `bytedcli lark auth status`
    的 identities.user.openId（已授权即可探测）。探测到即缓存，避免每次再问。"""
    if LARK_USER_ID:
        return LARK_USER_ID
    cached = load_json(IDENTITY_CACHE, default={}) or {}
    if cached.get("open_id"):
        return cached["open_id"]
    try:
        r = run([BYTEDCLI, "-j", "lark", "auth", "status"], timeout=40)
        d = json.loads(r.stdout or "{}")
        user = ((d or {}).get("identities") or {}).get("user") or {}
        oid = user.get("openId", "") or ""
        if oid:
            save_json(IDENTITY_CACHE, {"open_id": oid, "user_name": user.get("userName", ""),
                                       "at": now_utc().isoformat()})
            log(f"resolve_lark_user_id: 自动探测到 {user.get('userName','')} ({oid[:12]}…)")
            return oid
        log("resolve_lark_user_id: bytedcli auth status 未含 user.openId（可能未登录）")
    except Exception as e:
        log(f"resolve_lark_user_id 探测失败: {e!r}")
    return ""


def resolve_user_name() -> str:
    """当前用户显示名（零配置个性化）：config user_name → 缓存 → bytedcli auth status 的 userName。
    用于 prompt/文档标题里的称呼，绝不写死任何人名。探测不到返回空串（调用方用中性兜底）。"""
    name = _cfg("user_name")
    if name:
        return name
    cached = load_json(IDENTITY_CACHE, default={}) or {}
    if cached.get("user_name"):
        return cached["user_name"]
    resolve_lark_user_id()   # 触发探测，顺带缓存 user_name
    cached = load_json(IDENTITY_CACHE, default={}) or {}
    return cached.get("user_name", "") or ""


def lark_dm(markdown: str, idempotency_key: str, user_id: str = "",
            timeout: int = 60) -> bool:
    """用 bot 给本人发飞书 DM（markdown）。-j 取 JSON、--idempotency-key 防重。
    user_id 为空时自动探测本人 open_id（零配置）；仍探测不到才跳过。"""
    user_id = user_id or resolve_lark_user_id()
    if not user_id:
        log("lark_dm 跳过：未配置且无法自动探测 open_id（请确认 bytedcli 已完成飞书授权）")
        return False
    cmd = [BYTEDCLI, "-j", "lark", "im", "messages-send", "--as", "bot",
           "--user-id", user_id, "--markdown", markdown,
           "--idempotency-key", idempotency_key]
    r = run(cmd, timeout=timeout)
    try:
        data = json.loads(r.stdout)
    except Exception:
        log(f"lark_dm 解析失败: {(r.stdout or '')[:200]} {(r.stderr or '')[:200]}")
        return False
    if not isinstance(data, dict):   # 合法但非对象的 JSON（数字/数组）也按失败处理，不裸调 .get
        log(f"lark_dm 返回非对象 JSON: {str(data)[:200]}")
        return False
    if data.get("ok"):
        return True
    log(f"lark_dm 失败: {data.get('error') or (r.stderr or '')[:200]}")
    return False


def ensure_dirs():
    for d in (DATA_DIR, STATE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
