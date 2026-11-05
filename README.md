# djinni-mcp

> Personal project. I built it for myself and I'm still testing it — expect
> rough edges and breaking changes. Not affiliated with Djinni.

An MCP server that lets an AI assistant (Claude Code, Codex, any MCP client)
work with **your own** [Djinni](https://djinni.co) candidate account — profile,
inbox threads with recruiters, stats, recommended jobs — and search vacancies.

- Python 3 standard library only — no dependencies, Windows / macOS / Linux.
- 10 read tools, 4 write tools (`update_profile`, `send_message`,
  `apply_to_job`, `decline_offer`). Every write tool has `dry_run` and is
  annotated `readOnlyHint: false`, so the client can ask before each call.
- Links that change the account (`/my/stop/`, `/my/kill9/`, `?action=…`) are never opened.
- Paced requests (3–7 s), daily cap, stops on rate limits / captchas.

## Run

```sh
python server.py            # stdio MCP server
```

Credentials — environment or a `.env` file in this folder or above:

```
DJINNI_COOKIES=sessionid=...; csrftoken=...   # from your logged-in browser (DevTools → Cookies)
# or DJINNI_EMAIL=... and DJINNI_PASSWORD=...  # Djinni's own e-mail login
```

Claude Code (`.mcp.json`):

```json
{ "mcpServers": { "djinni": { "type": "stdio", "command": "python", "args": ["path/to/djinni-mcp/server.py"] } } }
```

Optional: `DJINNI_MCP_READ_ONLY=1` hides the write tools.

Allow the read tools and keep the write tools on "ask" — see the permissions
example and the full tool list in [AGENTS.md](AGENTS.md).

Use it only with your own account and at a human pace.
