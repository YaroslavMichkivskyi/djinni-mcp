# djinni-mcp

> Personal project. I built it for myself and I'm still testing it — expect
> rough edges and breaking changes. Not affiliated with Djinni.

An MCP server that lets an AI assistant (Claude Code, Codex, any MCP client)
read **your own** [Djinni](https://djinni.co) candidate account — profile,
inbox, conversations with recruiters — and search public vacancies.

- Python 3 standard library only — no dependencies, Windows / macOS / Linux.
- Read-only for now; write tools (reply, apply, edit profile) will come with
  `dry_run` and `readOnlyHint: false` annotations so the client asks first.
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

Tool list and permission setup: [AGENTS.md](AGENTS.md).

Use it only with your own account and at a human pace.
