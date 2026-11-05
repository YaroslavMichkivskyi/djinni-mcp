"""djinni-mcp — Djinni (djinni.co) as an MCP server: my candidate account
(profile, inbox, conversations, any account page) and public job search.

    python server.py [--env-file PATH] [--state-dir PATH]

Credentials (env or the nearest `.env`): DJINNI_EMAIL + DJINNI_PASSWORD, or
DJINNI_COOKIES (`sessionid=…; csrftoken=…` copied from a logged-in browser).
Read-only: no tool sends, applies, edits or raises anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mcpkit import (McpServer, SiteSession, Stop, clean, html_to_text, load_env, log, page_links,  # noqa: E402
                    page_main, page_title)

VERSION = "0.2.0"
BASE = "https://djinni.co"
HOSTS = ("djinni.co",)
# GET is not always harmless: links like these change account state.
UNSAFE_PATH = re.compile(r"logout|delete|remove|deactivat|unsubscrib|raise|apply|reject|accept|withdraw|toggle|"
                         r"/send|/\d+/(?:un)?(?:archive|hide|block|ban|read)\b", re.I)
ENGLISH = ("no_english", "basic", "pre", "intermediate", "upper", "fluent", "proficient", "native")
REGIONS = ("UKR", "eu", "worldwide", "other")

server = McpServer("djinni", VERSION, instructions=(
    "Djinni (Ukrainian IT job board) for the logged-in candidate. Every request is paced and counted against "
    "a daily budget — call `status` first. Never send, apply or edit on your own initiative."))
session: SiteSession  # set in main()


# ----------------------------------------------------------------- login ---

def _logged_in() -> tuple[bool, str]:
    final, _, page = session.request(f"{BASE}/my/profile/")
    ok = "/login" not in urllib.parse.urlsplit(final).path and 'name="password"' not in page
    return ok, page


def _account_name(page: str) -> str | None:
    m = re.search(r'name="(?:full_name|name|first_name)"[^>]*value="([^"]*)"', page)
    return clean(m.group(1)) if m and m.group(1) else None


def _login() -> dict:
    cookies = os.environ.get("DJINNI_COOKIES")
    email, password = os.environ.get("DJINNI_EMAIL"), os.environ.get("DJINNI_PASSWORD")
    if cookies:
        session.clear_cookies()
        n = session.import_cookie_header(cookies, ".djinni.co")
        method = f"cookies ({n})"
    elif email and password:
        session.clear_cookies()
        _, _, page = session.request(f"{BASE}/login")
        csrf = re.search(r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)", page)
        if not csrf:
            raise Stop("Djinni login form has no CSRF token — markup changed?")
        final, status, page = session.request(
            f"{BASE}/login", data={"csrfmiddlewaretoken": csrf.group(1), "email": email, "password": password},
            headers={"Referer": f"{BASE}/login", "Origin": BASE})
        if "/login" in urllib.parse.urlsplit(final).path and 'name="password"' in page:
            # the form re-renders with its empty-field hints and a generic "Помилка" title; keep the real message
            msgs = [clean(m) for m in re.findall(r'class="[^"]*(?:invalid-feedback|alert|errorlist)[^"]*"[^>]*>(.*?)</div>',
                                                  page, re.S)]
            msgs = [m for m in msgs if m and m not in ("Помилка", "Error") and "заповніть" not in m
                    and "fill" not in m.lower()]
            raise Stop("Djinni login failed: " + (msgs[0] if msgs else "unknown reason") +
                       " — if the account signs in with Google / LinkedIn / GitHub it may have no password: "
                       "set one via 'Забули пароль?' or use DJINNI_COOKIES")
        method = "password"
    else:
        raise Stop("no credentials: set DJINNI_COOKIES (or DJINNI_EMAIL + DJINNI_PASSWORD) in .env / the MCP config")
    ok, page = _logged_in()
    if not ok:
        raise Stop(f"Djinni login via {method} did not give an account session (cookies expired?)")
    return {"logged_in": True, "method": method, "name": _account_name(page)}


def _account_page(path_or_url: str) -> tuple[str, str]:
    """Fetch an account page, logging in once if the session expired."""
    url = urllib.parse.urljoin(BASE, path_or_url)
    if UNSAFE_PATH.search(urllib.parse.urlsplit(url).path):
        raise Stop(f"{url} looks like an action link (changes the account) — not opened")
    final, status, page = session.request(url)
    if "/login" in urllib.parse.urlsplit(final).path and "/login" not in url:
        log("session expired — logging in again")
        _login()
        final, status, page = session.request(url)
        if "/login" in urllib.parse.urlsplit(final).path:
            raise Stop("still redirected to login after logging in")
    if status >= 400:
        raise Stop(f"HTTP {status} on {url}")
    return final, page


def _page_result(final: str, page: str, offset: int, max_chars: int, links: bool) -> dict:
    text = html_to_text(page_main(page))
    out = {"url": final, "title": page_title(page), "chars": len(text),
           "text": text[offset:offset + max_chars]}
    if offset + max_chars < len(text):
        out["next_offset"] = offset + max_chars
    if links:
        out["links"] = page_links(page, final, HOSTS)
    return out


# ----------------------------------------------------------------- tools ---

PAGING = {
    "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "start of the text slice"},
    "max_chars": {"type": "integer", "minimum": 500, "maximum": 60000, "default": 15000},
    "links": {"type": "boolean", "default": False, "description": "also return the page's djinni.co links"},
}


@server.tool("status", "Is the Djinni session logged in, as whom; today's request budget. Costs 1 request.")
def status() -> dict:
    ok, page = _logged_in()
    return {"logged_in": ok, "name": _account_name(page) if ok else None,
            "credentials": [k for k in ("DJINNI_COOKIES", "DJINNI_EMAIL", "DJINNI_PASSWORD") if os.environ.get(k)],
            "budget": session.budget(), "hidden_tools": sorted(server.hidden), "version": VERSION}


@server.tool("login", "Log in with the configured credentials (password, else cookies). Never returns secrets.")
def login() -> dict:
    return _login()


@server.tool("get_page", "Read any djinni.co page in my account session as text (e.g. /my/dashboard/, "
             "/my/stats/, /my/inbox/?page=2). Action links (logout, delete, raise, apply…) are refused.",
             {"path": {"type": "string", "description": "path like /my/profile/ or a full https://djinni.co URL"},
              **PAGING}, ["path"])
def get_page(path: str, offset: int = 0, max_chars: int = 15000, links: bool = False) -> dict:
    final, page = _account_page(path)
    return _page_result(final, page, offset, max_chars, links)


@server.tool("my_profile", "My candidate profile form: title, category, experience, salary, English, "
             "skills, search status — field by field.")
def my_profile() -> dict:
    final, page = _account_page("/my/profile/")
    fields = {}
    tags = [(t.start(), "input", t.group(1), "") for t in re.finditer(r"<input\b([^>]*)>", page, re.I)]
    tags += [(t.start(), t.group(1).lower(), t.group(2), t.group(3))
             for t in re.finditer(r"<(textarea|select)\b([^>]*)>(.*?)</\1>", page, re.S | re.I)]
    for _, kind, attrs, inner in sorted(tags):
        name = re.search(r'name="([^"]+)"', attrs)
        if not name or name.group(1) in ("csrfmiddlewaretoken",) or "password" in name.group(1):
            continue
        typ = (re.search(r'type="([^"]+)"', attrs) or [None, "text"])[1]
        if kind == "select":
            sel = re.findall(r"<option[^>]*selected[^>]*>(.*?)</option>", inner, re.S)
            value = [clean(s) for s in sel] if sel else None
        elif kind == "textarea":
            value = html_to_text(inner)
        elif typ in ("checkbox", "radio"):
            if "checked" not in attrs:
                continue
            value = (re.search(r'value="([^"]*)"', attrs) or [None, True])[1]
        elif typ in ("hidden", "submit", "button", "file"):
            continue
        else:
            value = (re.search(r'value="([^"]*)"', attrs) or [None, ""])[1]
        key = name.group(1)
        if key in fields and typ == "checkbox":
            fields[key] = (fields[key] if isinstance(fields[key], list) else [fields[key]]) + [value]
        else:
            fields[key] = value
    return {"url": final, "fields": fields, "text": html_to_text(page_main(page))[:6000]}


@server.tool("inbox", "My Djinni inbox: conversations with recruiters (offers, replies to applications).",
             {"page": {"type": "integer", "minimum": 1, "default": 1},
              "filter": {"type": "string", "description": "optional query string from the inbox tabs, e.g. 'archive'"}})
def inbox(page: int = 1, filter: str | None = None) -> dict:
    qs = {k: v for k, v in (("page", page if page > 1 else None), ("filter", filter)) if v}
    final, html_page = _account_page("/my/inbox/" + (f"?{urllib.parse.urlencode(qs)}" if qs else ""))
    threads, seen = [], set()
    for m in re.finditer(r'href="(/my/inbox/(\d+)/?)"', html_page):
        if m.group(2) in seen:
            continue
        seen.add(m.group(2))
        # the card around the link: up to the next thread link
        start = m.start()
        nxt = re.search(r'href="/my/inbox/\d+/?"', html_page[m.end():])
        chunk = html_page[start:m.end() + (nxt.start() if nxt else 3000)]
        threads.append({"id": m.group(2), "url": BASE + m.group(1), "preview": clean(chunk)[:400]})
    out = {"url": final, "threads": threads}
    if not threads:
        out["text"] = html_to_text(page_main(html_page))[:8000]
    return out


@server.tool("conversation", "One inbox conversation: the vacancy and every message, oldest first.",
             {"thread_id": {"type": "string", "description": "id from `inbox`"}, **PAGING}, ["thread_id"])
def conversation(thread_id: str, offset: int = 0, max_chars: int = 15000, links: bool = False) -> dict:
    if not re.fullmatch(r"\d+", thread_id):
        raise Stop("thread_id must be the numeric id from `inbox`")
    final, page = _account_page(f"/my/inbox/{thread_id}/")
    return _page_result(final, page, offset, max_chars, links)


# ---------------------------------------------------------- public jobs ---

def _obj(value, key: str = "name") -> dict:
    if isinstance(value, dict):
        return value
    return {key: value} if isinstance(value, (str, int, float)) else {}


def _postings(page: str) -> list[dict]:
    out = []
    for block in re.findall(r'<script type="application/ld\+json">\s*(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for p in data if isinstance(data, list) else [data]:
            if not isinstance(p, dict) or p.get("@type") != "JobPosting":
                continue
            base = _obj(p.get("baseSalary"), "value")
            salary = _obj(base.get("value"), "value")
            months = _obj(p.get("experienceRequirements"), "monthsOfExperience").get("monthsOfExperience")
            out.append({
                "id": str(p.get("identifier")), "url": p.get("url"), "title": p.get("title"),
                "company": _obj(p.get("hiringOrganization")).get("name"),
                "salary": {"min": salary.get("minValue"), "max": salary.get("maxValue"), "currency": base.get("currency")}
                if salary.get("minValue") or salary.get("maxValue") else None,
                "experience_years": round(float(months) / 12, 1) if months is not None else None,
                "remote": p.get("jobLocationType") == "TELECOMMUTE",
                "posted_at": (p.get("datePosted") or "")[:10] or None,
                "category": p.get("category"),
                "description": html_to_text(p.get("description") or ""),
            })
    return out


@server.tool("search_jobs", "Public Djinni job search (no login needed). ~15 vacancies per page with a short "
             "description; use get_job for the full text.",
             {"keywords": {"type": "array", "items": {"type": "string"},
                           "description": "Djinni categories (primary_keyword): JavaScript, Node.js, Fullstack…"},
              "search": {"type": "string", "description": "free text (all_keywords)"},
              "experience": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 10},
                             "description": "years buckets: 0 = no experience, 1…10"},
              "remote": {"type": "boolean", "default": False},
              "english": {"type": "string", "enum": list(ENGLISH)},
              "region": {"type": "array", "items": {"type": "string", "enum": list(REGIONS)}},
              "page": {"type": "integer", "minimum": 1, "default": 1},
              "description_chars": {"type": "integer", "minimum": 0, "maximum": 5000, "default": 600}})
def search_jobs(keywords: list[str] | None = None, search: str | None = None, experience: list[int] | None = None,
                remote: bool = False, english: str | None = None, region: list[str] | None = None,
                page: int = 1, description_chars: int = 600) -> dict:
    params = [("primary_keyword", k) for k in keywords or []]
    params += [("exp_level", "no_exp" if y == 0 else f"{y}y") for y in experience or []]
    if search:
        params.append(("all_keywords", search))
    if remote:
        params.append(("employment", "remote"))
    if english:
        params.append(("english_level", english))
    params += [("region", r) for r in region or []]
    if page > 1:
        params.append(("page", page))
    url = f"{BASE}/jobs/?{urllib.parse.urlencode(params)}"
    _, _, html_page = session.request(url)
    jobs = _postings(html_page)
    cards = len(set(re.findall(r'id="job-item-(\d+)"', html_page)))
    if cards and not jobs:
        raise Stop(f"page has {cards} job cards but no structured data — markup changed?")
    for j in jobs:
        j["description"] = j["description"][:description_chars]
    return {"url": url, "page": page, "count": len(jobs), "has_next": f"page={page + 1}" in html_page, "jobs": jobs}


@server.tool("get_job", "Full text of one public Djinni vacancy.",
             {"url": {"type": "string", "description": "the vacancy URL, https://djinni.co/jobs/<id>-<slug>/ "
                                                       "(as returned by search_jobs)"}}, ["url"], title="Vacancy")
def get_job(url: str) -> dict:
    m = re.match(r"https://djinni\.co/jobs/(\d+)-[^/?#]+/?", url.strip())
    if not m:
        raise Stop("give the full vacancy URL https://djinni.co/jobs/<id>-<slug>/ (a bare id gives 404 on Djinni)")
    final, status, html_page = session.request(url.strip())
    if status >= 400:
        raise Stop(f"HTTP {status} on {url} — vacancy closed or the URL is wrong")
    jobs = _postings(html_page)
    out = jobs[0] if jobs else {"id": m.group(1)}
    out["url"] = final
    if not jobs:
        out["text"] = html_to_text(page_main(html_page))[:20000]
    return out


# ------------------------------------------------------------------ main ---

def main() -> None:
    global session
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="read credentials from this file (default: nearest .env upwards)")
    ap.add_argument("--state-dir", help="cookies + request ledger (default: DJINNI_MCP_STATE_DIR or <this folder>/.state)")
    args = ap.parse_args()
    env = load_env(HERE, args.env_file)
    log(f"env file: {env or 'none'}")
    state = Path(args.state_dir or os.environ.get("DJINNI_MCP_STATE_DIR") or HERE / ".state")
    session = SiteSession("djinni", state, HOSTS,
                          delay=(3.0, 7.0), daily=int(os.environ.get("DJINNI_MCP_DAILY", "150")))
    server.run()


if __name__ == "__main__":
    main()
