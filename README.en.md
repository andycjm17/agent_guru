<!-- English | [中文](README.md) -->

# workflow-distiller

workflow-distiller observes your AI coding sessions and distills recurring workflows into four categories — **Eliminate / Automate / Skill / Human** — then generates runnable Skills and automations directly, shifting your effort toward the irreplaceable human judgment.

- **Pluggable, not tied to one platform**
  - Observation sources: Claude Code / Cursor / Codex (any one or several; also the Skill target)
  - Delivery channels: Feishu / local file / Slack
  - LLM backends: Claude / ByteDance AIME / Mira gateway
- **Zero-config startup**: platforms and identity are auto-detected, documents are created on first use, no personal data is hardcoded.
- **Pure standard library**: Python ≥ 3.9, no pip dependencies.

For deployment, see [SETUP.en.md](SETUP.en.md).

## Quick start

```bash
# 1. (Optional) Choose platforms: observation sources / delivery channels / default target
python3 -m distiller.setup               # or configure in the Dashboard "⚙ Settings"

# 2. Run the main pipeline: observe → distill → deliver to enabled channels
python3 -m distiller.pipeline            # add --no-lark to generate results without delivering

# 3. Open the local Dashboard
python3 -m distiller.server              # http://127.0.0.1:8787

# 4. Generate this week's report draft
python3 -m distiller.weekly_update       # add --approve to push to the report document

# 5. Weekly retrospective
python3 -m distiller.retro --dry-run     # remove --dry-run to send for real
```

## How it works

Each step of a recurring workflow is placed into one of four categories, with automation increasing along an autonomy gradient:

| Category | Criterion | Output |
|---|---|---|
| Eliminate | Unused / legacy overhead | Recommendation to stop |
| Automate | Deterministic, rule-based, same input → same output | Script / launchd job |
| Skill | Requires judgment but is distillable and reusable | `SKILL.md` |
| Human | Interpersonal / trust / accountability / decisions | Explicitly flagged, left to a person |

**Autonomy gradient** (configured per item in the Dashboard): Suggest → Draft for review → Auto + notify → Fully automatic.

The pipeline has three stages: **Observe** (collect session summaries) → **Distill** (LLM clusters workflows and categorizes them) → **Deliver** (generate the Workflow Map, Skills, and reports, then send to enabled channels).

## Dashboard

`python3 -m distiller.server` opens `http://127.0.0.1:8787`:

- **Usage overview**: measured counts from session logs (Skill invocations, automation runs). Time saved is shown as a clearly-labeled estimate, for reference only.
- **Workflow Map**: click any row to expand its step breakdown and recommendation; "Distill into Skill" generates a SKILL.md draft from that workflow.
- **Skills**: click any row to edit the SKILL.md and autonomy; "Apply to production" backs up the previous version before writing to the target platform.
- **⚙ Settings**: configure observation sources, delivery channels, default target platform, and Slack Webhook; saved changes take effect immediately.

A language toggle (中 / EN) in the top bar switches the interface and remembers your choice.

## Components

| Module | Responsibility |
|---|---|
| `config.py` | Shared foundation: paths, constants, CLI resolution, LLM abstraction (Claude/AIME/Mira), config I/O and backups |
| `agents/` | Pluggable Agent platforms (`claude_code` / `cursor` / `codex`): observation sources, also Skill targets |
| `sinks/` | Pluggable delivery channels (`feishu` / `local` / `slack`): `broadcast_dm` / `broadcast_report` |
| `observe.py` | Iterate enabled sources, collect session summaries into `digests.json` (summaries only, with source counts) |
| `distill.py` | Cluster summaries into recurring workflows via the LLM and categorize them, producing `map.json` |
| `render.py` | Render `map.json` to DocxXML (Feishu) and Markdown (local/Slack), deliver to enabled channels |
| `usage.py` | Count Skill invocations from session logs (measured) |
| `savings.py` | Time-saved ledger: record real automation runs, output net values and overview |
| `server.py` + `ui/` | Local Dashboard: usage overview, Workflow Map, Skills editor, platform settings |
| `setup.py` | Platform selection wizard: detect available platforms, write to `config.local.json` |
| `weekly_update.py` | Aggregate this week's signals into a structured report; push with `--approve` |
| `retro.py` | Re-run observe and distill, diff new workflows, send the weekly retrospective |
| `doctor.py` | Environment self-check: verify dependencies, platforms, channels; separate blockers from degradations; `--fix` auto-installs the automatable missing pieces |
| `pipeline.py` | Main pipeline orchestration: observe → distill → deliver |

## Scheduled retrospective (optional)

`install.sh` offers one-click setup, or generate a launchd job manually (placeholders auto-filled):

```bash
sed -e "s#__PROJECT_ROOT__#$(pwd)#g" -e "s#__PYTHON__#$(command -v python3)#g" -e "s#__HOME__#$HOME#g" \
    com.workflow-distiller.plist.template > ~/Library/LaunchAgents/com.workflow-distiller.plist
launchctl load ~/Library/LaunchAgents/com.workflow-distiller.plist   # triggers retro Mondays at 09:00
```

## Design principles

- **Only act on what is observable.** What an Agent cannot see (hallway conversations, decisions made in meetings) is the irreplaceable human part; the tool does not touch it.
- **Honest measurement.** The Dashboard leads with measured counts; time saved is a counterfactual estimate, marked `~` and allowed to be negative — never a vanity metric.
- **Read-only on session history**; no existing session is ever modified.
