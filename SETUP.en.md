<!-- English | [中文](SETUP.md) -->

# Deployment guide

Deploy workflow-distiller to your local environment. After completing Feishu + bytedcli authorization, it works out of the box — identity is auto-detected and the report document is created on first use, with no IDs or URLs to fill in manually.

## Prerequisites

1. **Node.js / npm**: used to install bytedcli.
2. **bytedcli (Feishu authorized)**:

   ```bash
   npm install -g @bytedance-dev/bytedcli@latest --registry https://bnpm.byted.org
   bytedcli lark auth login
   ```

   The tool uses this to obtain your Feishu `open_id` (DM recipient) and document read/write access. If missing, `install.sh` installs it automatically.

3. **At least one AI coding environment**: Claude Code (`~/.claude/projects`), Cursor, or Codex CLI (`~/.codex/sessions`). The tool observes the sessions there as input; without any of them there is no observable data.

> **Pluggable design**
> - Observation sources: Claude Code / Cursor / Codex — any one or several, auto-detected. Sources also serve as Skill targets.
> - Delivery channels: Feishu / local file (`data/out/`, zero-dependency) / Slack (enabled once a Webhook is provided).
> - LLM backend: prefers local `claude`; falls back to ByteDance AIME (bundled with bytedcli), or configure `mira_endpoint` for a Mira / ModelHub gateway.
>
> Platform selection can be done via the `python3 -m distiller.setup` wizard or the Dashboard "⚙ Settings" — both write to the same configuration. The tool depends only on the Python standard library (≥ 3.9) and installs no pip packages; `lark-cli` ships with bytedcli.

## Installation

```bash
tar -xzf workflow-distiller-v1.tar.gz
cd workflow-distiller-v1
./install.sh            # detect CLIs, verify Feishu auth, create directories, run self-check (optional scheduled retro)
```

No configuration is required to start (platforms are auto-detected by default):

```bash
python3 -m distiller.setup           # optional: platform selection wizard
python3 -m distiller.pipeline        # observe → distill → generate the Workflow Map and deliver
python3 -m distiller.server          # local Dashboard
python3 -m distiller.weekly_update --approve   # report: pinned-append for Feishu, written to local / Slack otherwise
python3 -m distiller.retro --dry-run # preview the weekly retro; remove --dry-run to send
```

Run the environment self-check anytime: `python3 -m distiller.doctor`; add `--fix` to auto-install the automatable missing pieces after detection (create directories, `npm`-install bytedcli), or `--fix -y` to skip the prompt (non-interactive/CI). Feishu SSO login is interactive and cannot be automated — the command is only printed as a hint.

## Dashboard

`python3 -m distiller.server` opens `http://127.0.0.1:8787`:

- **Workflow Map**: click any row to expand its step breakdown and recommendation. "Distill into Skill" generates a SKILL.md draft from that workflow; edit it, then apply.
- **Skills**: click any row to edit the SKILL.md and autonomy. "Apply to production" backs up the previous version to `data/backups/`, then atomically writes to the target platform's path:
  - Claude Code: `~/.claude/skills/<name>/SKILL.md`
  - Cursor: `.cursor/rules/<name>.mdc`
  - Codex: `~/.codex/prompts/<name>.md`
- **⚙ Settings**: configure observation sources, delivery channels, default target platform, and Slack Webhook; saved changes take effect immediately.

A language toggle (中 / EN) in the top bar switches the interface and remembers your choice.

## Zero-config mechanisms

| Item | Mechanism |
|---|---|
| Feishu open_id (DM recipient) | Auto-detected at runtime from `bytedcli lark auth status`, cached to `data/identity.json` |
| Report document | Created automatically on first `weekly_update --approve`, token saved and reused |
| Map document | Created automatically on first `pipeline` / `render`, token saved and updated thereafter |
| `claude` / `lark-cli` / `bytedcli` paths | Auto-detected via `which` |

## Optional configuration

All fields are optional. To override defaults, copy `config.local.example.json` to `config.local.json` and fill in:

| Field | Description | Default |
|---|---|---|
| `sources` | Enabled observation sources (`claude_code` / `cursor` / `codex`) | auto-detect all available |
| `sinks` | Enabled delivery channels (`feishu` / `local` / `slack`) | Feishu if available, otherwise local |
| `skill_target` | Default target platform for "Apply to production" | first writable enabled platform |
| `slack_webhook` | Slack Incoming Webhook URL | Slack skipped if unset |
| `cursor_rules_dir` | Cursor `.mdc` target directory | `~/.cursor/rules` |
| `tracked_people` | People listed separately under dev follow-ups in the report | section omitted |
| `ui_port` | Dashboard port | 8787 |
| `weekly_doc_url` | Use an existing report document | created on first use |
| `lark_user_id` | Specify the DM recipient | auto-detect current user |
| `claude_path` / `lark_cli_path` / `bytedcli_path` | Non-standard CLI install paths | detected via `which` |
| `meeting_state_file` | Merge in meeting-actions data | disabled |

Fields can also be overridden by environment variables (e.g. `WD_UI_PORT`), or point `WD_CONFIG=/path.json` at a config file.

## Scheduled retrospective (optional)

Install via `install.sh`, or generate a launchd job manually:

```bash
sed -e "s#__PROJECT_ROOT__#$(pwd)#g" -e "s#__PYTHON__#$(command -v python3)#g" -e "s#__HOME__#$HOME#g" \
    com.workflow-distiller.plist.template > ~/Library/LaunchAgents/com.workflow-distiller.plist
launchctl load ~/Library/LaunchAgents/com.workflow-distiller.plist   # Mondays at 09:00
```

## Privacy and boundaries

- Everything runs locally; the Dashboard binds to `127.0.0.1` and is not exposed externally.
- `config.local.json` and `data/` (including document tokens and `identity.json`) are excluded from version control and the installation package by default.
- The Dashboard leads with measured counts; time saved is an estimate (marked `~`, can be negative), never a vanity metric.
- Session history is read-only; no existing session is modified.

## Repackaging

```bash
./package.sh v1      # produces dist/workflow-distiller-v1.tar.gz (personal config, tokens, and data automatically excluded)
```
