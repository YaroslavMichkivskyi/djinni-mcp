---
kind: tool
about: Djinni (djinni.co) as an MCP server — my candidate account (profile, inbox, conversations, any account page) and public job search
when: reading my Djinni account (profile settings, recruiter offers, conversations) or looking up Djinni vacancies
---

# djinni-mcp — Djinni as an MCP server

Stdio MCP server, Python 3 standard library only (Windows / macOS / Linux).
Acts as the logged-in Djinni candidate. A Spiritus **module** (`kind: tool`):
installed into `arsenal/djinni-mcp/` with `spiritus run modules:install djinni-mcp`;
nothing here depends on the rest of Spiritus, so it also runs standalone.
For people: `README.md`.

| File | What |
|---|---|
| `server.py` | the tools below, Djinni login and parsing |
| `mcpkit.py` | shared kit: MCP stdio + tool annotations + read-only switches, paced cookie session, forms, `.env` loader, HTML → text. Identical copy in `dou-mcp` — change one, copy to the other |
| `.state/` | cookies + request ledger (gitignored; `--state-dir` / `DJINNI_MCP_STATE_DIR`) |

## Tools

All read-only for now (`readOnlyHint: true`):

| Tool | Gives | Requests |
|---|---|---|
| `status` | logged in? as whom, budget, hidden tools | 1 |
| `login` | re-login from the configured credentials | 1–3 |
| `my_profile` | my profile form, field by field | 1 |
| `inbox` | conversation list (`page`, `filter`) | 1 |
| `conversation` | one thread as text | 1 |
| `get_page` | any djinni.co page as text (+ links), e.g. `/my/dashboard/`; action links refused | 1 |
| `search_jobs` | public search: categories, experience years, remote, English, region, text; ~15 / page | 1 |
| `get_job` | full vacancy (by its URL) | 1 |

**Status:** the account tools are written but not yet verified against a
live session (the password login was refused; cookies pending). Write tools
(reply, apply, edit profile, raise profile) come after that, built like
`dou-mcp`'s: separate tools, `dry_run`, `readOnlyHint: false`.

## Config

| Env (or the nearest `.env` above the folder; env wins) | |
|---|---|
| `DJINNI_COOKIES` | `sessionid=…; csrftoken=…` from a logged-in browser (DevTools → Application → Cookies → djinni.co); preferred |
| `DJINNI_EMAIL`, `DJINNI_PASSWORD` | Djinni's own e-mail login (accounts made with Google / LinkedIn / GitHub have no password until one is set via "Забули пароль?") |
| `DJINNI_MCP_READ_ONLY=1` | write tools are not listed |
| `DJINNI_MCP_DISABLED_TOOLS=a,b` | hide these tools |
| `DJINNI_MCP_DAILY` | daily request cap, default 150 |

Claude Code `.mcp.json`: `"djinni": {"type": "stdio", "command": "python", "args": ["arsenal/djinni-mcp/server.py"]}`.
Codex `config.toml`: `[mcp_servers.djinni]`, `command = "python"`, `args = ["<repo>/arsenal/djinni-mcp/server.py"]`.

Per-tool permissions in Claude Code (`.claude/settings.json`): list read
tools under `permissions.allow` (`"mcp__djinni__search_jobs"`, …) and write
tools, once they exist, under `ask`; `"mcp__djinni"` alone matches every tool.

## Rules

- Write tools (when added) act as me: `dry_run` first, explicit OK, one call.
- Anti-ban: one request at a time, 3–7 s jittered pause (kept across calls and
  restarts), daily cap; 403 / 429 / captcha stops the call — don't loop.
  Bulk collection belongs to a collector with its own budget.
- Djinni's ToS don't allow automated access: my own account, low volume.
  Never print, log or return credentials or cookies.
