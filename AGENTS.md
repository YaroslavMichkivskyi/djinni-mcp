---
kind: tool
about: Djinni (djinni.co) as an MCP server — my candidate account (profile, inbox threads, stats, recommended jobs) with write tools behind dry_run, and job search
when: reading or acting on my Djinni account (offers, applications, threads, profile, stats), or looking up Djinni vacancies
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

Read — annotated `readOnlyHint: true`:

| Tool | Gives | Requests |
|---|---|---|
| `status` | logged in? budget, hidden tools | 1 |
| `login` | re-login from the configured credentials | 1–3 |
| `get_profile` | every profile field with value, label and options; when the profile can be raised again | 1 |
| `list_threads` | inbox: company, recruiter, vacancy, last message, read receipt (`bucket` all / unread / apply / archive, `search`, `page`) | 1 |
| `get_thread` | vacancy card (conditions, CV shared, salary notes) + messages (author, time, notes, text) | 1 |
| `get_stats` | contacts in 3 months vs hired peers, offers, applications sent / read | 1 |
| `get_recommended_jobs` | the "Вакансії" dashboard for my profile | 1 |
| `search_jobs` | categories, experience years, remote, English, region, salary from, text; ~15 / page | 1 |
| `get_job` | full vacancy + `can_apply` / existing `thread`, my CVs, profile salary | 1 |
| `get_page` | any djinni.co page as text (+ links); action links refused | 1 |

Write — `readOnlyHint: false`, each with `dry_run` (returns the exact payload, sends nothing):

| Tool | Does | Hints |
|---|---|---|
| `update_profile` | change profile fields by name (others keep their values; options validated); `add_skills` / `remove_skills` for skill chips — Djinni renames new skills to its own dictionary entries, so check `get_profile` after | destructive, idempotent |
| `send_message` | reply in a thread; verifies the new message appeared | not idempotent |
| `apply_to_job` | apply with a message, chosen CV, optional salary for this vacancy; refuses a repeat | not idempotent |
| `decline_offer` | decline + archive a recruiter's offer | destructive, idempotent |

Not exposed on purpose: raising the profile (Djinni allows it once per
cooldown and gives no stable endpoint while it is locked), switching the search
off (`/my/stop/`), deleting the account (`/my/kill9/`), reporting a hire.

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

Per-tool permissions in Claude Code (`.claude/settings.json` or `settings.local.json`):

```json
{ "permissions": {
    "allow": ["mcp__djinni__status", "mcp__djinni__login", "mcp__djinni__get_profile",
              "mcp__djinni__list_threads", "mcp__djinni__get_thread", "mcp__djinni__get_stats",
              "mcp__djinni__get_recommended_jobs", "mcp__djinni__search_jobs", "mcp__djinni__get_job",
              "mcp__djinni__get_page"],
    "ask":   ["mcp__djinni__update_profile", "mcp__djinni__send_message",
              "mcp__djinni__apply_to_job", "mcp__djinni__decline_offer"] } }
```

`deny` instead of `ask` blocks a tool; other clients get the same split from
the tool annotations or from `DJINNI_MCP_READ_ONLY`.

## Rules

- Write tools act as me: show me the `dry_run` payload, wait for an explicit OK,
  then call once. Never retry a send / apply blindly — check `get_thread` /
  `list_threads(bucket='apply')` first.
- Anti-ban: one request at a time, 3–7 s jittered pause (kept across calls and
  restarts), daily cap; 403 / 429 / captcha stops the call — don't loop.
  Bulk collection belongs to a collector with its own budget.
- Djinni's ToS don't allow automated access: my own account, low volume.
  Never print, log or return credentials or cookies.
