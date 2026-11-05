"""djinni-mcp — Djinni (djinni.co) as an MCP server.

    python server.py [--env-file PATH] [--state-dir PATH]

Account: candidate profile, inbox (offers and my applications) and threads,
stats, jobs recommended for my profile — read, and (separate tools, each with
`dry_run`) edit the profile, reply in a thread, apply to a vacancy, decline an
offer. Public: job search and vacancy text.

Credentials (env or the nearest `.env`): DJINNI_COOKIES (`sessionid=…;
csrftoken=…` from a logged-in browser) or DJINNI_EMAIL + DJINNI_PASSWORD.
Switches: DJINNI_MCP_READ_ONLY=1, DJINNI_MCP_DISABLED_TOOLS=a,b, DJINNI_MCP_DAILY=150.
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
from mcpkit import (DRY_RUN_PROP, PAGING_PROPS, McpServer, SiteSession, Stop, attr, clean,  # noqa: E402
                    csrf_token, html_to_text, is_action_link, load_env, log, override_form, page_links, page_main,
                    page_title, parse_form, slice_text)

VERSION = "0.3.1"
BASE = "https://djinni.co"
HOSTS = ("djinni.co",)
# Plain GET links that change the account: /my/kill9/ deletes it, /my/stop/ switches the search off,
# ?action=decline archives a thread.
ACTION_SEGMENTS = re.compile(r"logout.*|kill\d*|stop|delete.*|remove.*|deactivat.*|unsubscrib.*|raise|reactivat.*|"
                             r"apply|reject|accept|withdraw|toggle.*|send|htmx|ajax|(?:un)?archive|hide|block|ban|"
                             r"(?:mark_)?(?:un)?read", re.I)
ENGLISH = ("no_english", "basic", "pre", "intermediate", "upper", "fluent", "proficient", "native")
REGIONS = ("UKR", "eu", "worldwide", "other")
BUCKETS = ("all", "unread", "apply", "archive")

server = McpServer("djinni", VERSION, instructions=(
    "Djinni (Ukrainian IT job board) for the logged-in candidate. Read tools are free to call but every request "
    "is paced and counted against a daily budget — call `status` first. Write tools (update_profile, "
    "send_message, apply_to_job, decline_offer) act as the user: show the dry_run payload, get an explicit OK, "
    "then call once. Never send, apply or decline on your own initiative."))
session: SiteSession  # set in main()

DRY_RUN, PAGING = DRY_RUN_PROP, PAGING_PROPS
NAV_NOISE = re.compile(r"^.*?(?:Акаунт рекрутера|Recruiter account)\s*-?\s*(?:Вийти|Log out)\s*", re.S)


# ---------------------------------------------------------------- helpers ---

def _is_login(final: str, page: str) -> bool:
    return "/login" in urllib.parse.urlsplit(final).path or ('name="password"' in page and 'id="signup"' in page)


_csrf, _slice = csrf_token, slice_text


def _text(page: str) -> str:
    text = NAV_NOISE.sub("", html_to_text(page_main(page)), count=1)
    return re.sub(r"^\s*Помилка\s*", "", text)


def _thread_id(value: str) -> str:
    m = re.search(r"(?:^|/inbox/)(\d+)", str(value).strip())
    if not m:
        raise Stop("thread must be the numeric id from list_threads (or its /my/inbox/<id>/ URL)")
    return m.group(1)


def _job_url(url: str) -> str:
    m = re.match(r"https://djinni\.co/jobs/(\d+)-[^/?#]+/?", (url or "").strip())
    if not m:
        raise Stop("give the full vacancy URL https://djinni.co/jobs/<id>-<slug>/ (a bare id gives 404 on Djinni)")
    return m.group(0).rstrip("/") + "/"


def _sidebar(page: str) -> str | None:
    side = re.search(r"<sidebar\b[^>]*>(.*?)</sidebar>", page, re.S)
    return html_to_text(side.group(1)) if side else None


# ------------------------------------------------------------------ login ---

def _logged_in() -> tuple[bool, str]:
    final, _, page = session.request(f"{BASE}/my/profile/")
    return not _is_login(final, page), page


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
        final, _, page = session.request(
            f"{BASE}/login", data={"csrfmiddlewaretoken": _csrf(page), "email": email, "password": password},
            headers={"Referer": f"{BASE}/login", "Origin": BASE})
        if _is_login(final, page):
            # the form re-renders with empty-field hints and a generic "Помилка" title; keep the real message
            msgs = [clean(m) for m in re.findall(r'class="[^"]*(?:invalid-feedback|alert|errorlist)[^"]*"[^>]*>(.*?)</div>',
                                                  page, re.S)]
            msgs = [m for m in msgs if m and m not in ("Помилка", "Error") and "заповніть" not in m
                    and "fill" not in m.lower()]
            raise Stop("Djinni login failed: " + (msgs[0] if msgs else "unknown reason") +
                       " — accounts made with Google / LinkedIn / GitHub have no password until one is set "
                       "via 'Забули пароль?'; or use DJINNI_COOKIES")
        method = "password"
    else:
        raise Stop("no credentials: set DJINNI_COOKIES or DJINNI_EMAIL + DJINNI_PASSWORD in .env / the MCP config")
    ok, _ = _logged_in()
    if not ok:
        raise Stop(f"Djinni login via {method} did not give an account session (cookies expired?)")
    return {"logged_in": True, "method": method}


def _get(path_or_url: str) -> tuple[str, str]:
    """GET a djinni.co page in my session; logs in once if the session is gone."""
    url = urllib.parse.urljoin(BASE, path_or_url)
    parts = urllib.parse.urlsplit(url)
    if is_action_link(url, ACTION_SEGMENTS):
        raise Stop(f"{url} looks like an action link (changes the account) — not opened")
    final, status, page = session.request(url)
    if _is_login(final, page) and "/login" not in parts.path:
        log("session expired — logging in again")
        _login()
        final, status, page = session.request(url)
        if _is_login(final, page):
            raise Stop("still redirected to login after logging in")
    if status >= 400:
        raise Stop(f"HTTP {status} on {url}")
    return final, page


# -------------------------------------------------------------- account ---

@server.tool("status", "Is the Djinni session logged in; today's request budget. 1 request.", title="Session status")
def status() -> dict:
    ok, _ = _logged_in()
    return {"logged_in": ok,
            "credentials": [k for k in ("DJINNI_COOKIES", "DJINNI_EMAIL", "DJINNI_PASSWORD") if os.environ.get(k)],
            "budget": session.budget(), "hidden_tools": sorted(server.hidden), "version": VERSION}


@server.tool("login", "Log in again with the configured credentials (cookies, else password). Never returns secrets.",
             title="Log in")
def login() -> dict:
    return _login()


def _profile_form() -> tuple[str, dict, str]:
    final, page = _get("/my/profile/")
    form = re.search(r'<form\b[^>]*id="js-profile-form"[^>]*>(.*?)</form>', page, re.S)
    if not form:
        raise Stop("profile form not found on /my/profile/ — markup changed?")
    parsed = parse_form(form.group(1))
    labels = {i: clean(t) for i, t in re.findall(r'<label[^>]*for="([^"]+)"[^>]*>(.*?)</label>', form.group(1), re.S)}
    id_of = {}
    for attrs in re.findall(r"<input\b([^>]*)>", form.group(1)):
        i, n, v = (re.search(rf'\b{a}="([^"]*)"', attrs) for a in ("id", "name", "value"))
        if i and n:
            id_of[(n.group(1), v.group(1) if v else "on")] = i.group(1)
    for name, f in parsed["fields"].items():
        if f["type"] in ("checkbox", "radio") and f.get("options"):
            f["options"] = [{"value": v, "label": labels.get(id_of.get((name, v), ""), v)} for v in f["options"]]
    return final, parsed, page


@server.tool("get_profile", "My candidate profile: every field of the profile form (position, primary keyword, "
             "experience, salary, English and other languages, skills with years, location, formats, highlights, "
             "about, looking for, mobilization deferment…) with current values and options, plus when the profile "
             "can be raised in search again.", title="My profile")
def get_profile() -> dict:
    final, parsed, page = _profile_form()
    i = page.find("можна знову оновити")
    near = clean(page[max(0, i - 400):i + 300]) if i >= 0 else ""
    m = re.search(r"Востаннє.*?дн\.|Last raised.*?days?", near)
    raise_info = m.group(0) if m else None
    fields = {k: v for k, v in parsed["fields"].items() if k != "csrfmiddlewaretoken"}
    return {"url": final, "raise_info": raise_info, "fields": fields}


def _threads(page: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<div\s+id="mt-(\d+)"\s+data-id="\d+"\s+class="proposal([^"]*)"(.*?)'
                         r'(?=<div class="thread-item-wrapper|<div\s+id="mt-\d+"|\Z)', page, re.S):
        body = m.group(3)
        company = re.search(r'class="company_name[^"]*">(.*?)</div>', body, re.S)
        names = [clean(s) for s in re.findall(r"<span>(.*?)</span>", company.group(1), re.S)] if company else []
        names = [n for n in names if n and n != "·"]
        title = re.search(r'<a class="to-job"[^>]*>(.*?)</a>', body, re.S)
        last = re.search(r'class="message-text-inner[^"]*"[^>]*>(.*?)</a>', body, re.S)
        date = re.search(r'class="small ms-1 js-date-value"[^>]*>(.*?)</span>\s*</div>', body, re.S)
        read = re.search(r'title="((?:Прочитано|Read)[^"]*)"', body)
        out.append({
            "id": m.group(1), "url": f"{BASE}/my/inbox/{m.group(1)}/",
            "company": names[0] if names else None, "recruiter": names[1] if len(names) > 1 else None,
            "job": clean(title.group(1)) if title else None,
            "last_message": clean(last.group(1)) if last else None,
            "when": clean(date.group(1)) if date else None,
            "read_by_them": read.group(1) if read else None,
            "unread": "unread" in m.group(2),
        })
    return out


@server.tool("list_threads", "My Djinni inbox: offers from recruiters and my applications — company, recruiter, "
             "vacancy, last message, when, whether they read it.",
             {"bucket": {"type": "string", "enum": list(BUCKETS), "default": "all",
                         "description": "all; unread; apply = my applications waiting for an answer; archive"},
              "search": {"type": "string", "description": "inbox search text"},
              "page": {"type": "integer", "minimum": 1, "default": 1}}, title="Inbox")
def list_threads(bucket: str = "all", search: str | None = None, page: int = 1) -> dict:
    qs = {k: v for k, v in (("bucket", None if bucket == "all" else bucket), ("q", search),
                            ("page", page if page > 1 else None)) if v}
    final, html_page = _get("/my/inbox/" + (f"?{urllib.parse.urlencode(qs)}" if qs else ""))
    threads = _threads(html_page)
    return {"url": final, "bucket": bucket, "count": len(threads),
            "has_next": f"page={page + 1}" in html_page, "threads": threads}


def _messages(page: str) -> list[dict]:
    msgs = []
    for m in re.finditer(r'<div\s+id="msg_(\d+)"\s+class="thread-message[^"]*"[^>]*>(.*?)'
                         r'(?=<div\s+id="msg_\d+"\s+class="thread-message|<form\b|\Z)', page, re.S):
        body = m.group(2)
        author = re.search(r'class="font-weight-500 ms-2">(.*?)</div>', body, re.S)
        when = re.search(r'<small\s+class="text-secondary"[^>]*?title="([^"]+)"', body)
        alerts = [clean(a) for a in re.findall(r'class="msg-alert[^"]*">(.*?)</div>', body, re.S)]
        text = re.search(r'class="thread-message-body[^"]*">\s*<div>(.*?)</div>', body, re.S) or \
            re.search(r'class="thread-message-body[^"]*">(.*?)</div>', body, re.S)
        msgs.append({"id": m.group(1), "author": clean(author.group(1)) if author else None,
                     "time": when.group(1) if when else None, "notes": [a for a in alerts if a] or None,
                     "text": html_to_text(text.group(1)) if text else None})
    return msgs


@server.tool("get_thread", "One inbox thread: the vacancy card (company, recruiter, conditions, CV shared, salary "
             "notes) and every message (id, author, time, text, notes like 'Ви відгукнулись').",
             {"thread": {"type": "string", "description": "id from list_threads"},
              "last": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50}}, ["thread"],
             title="Inbox thread")
def get_thread(thread: str, last: int = 50) -> dict:
    tid = _thread_id(thread)
    final, page = _get(f"/my/inbox/{tid}/")
    msgs = _messages(page)
    return {"url": final, "thread": tid, "vacancy_card": _sidebar(page), "count": len(msgs),
            "messages": msgs[-last:], "can_reply": "js-inbox-reply-form" in page}


@server.tool("get_stats", "My Djinni stats: contacts with companies in 3 months vs similar hired candidates, "
             "offers received, applications sent and read, how often recruiters read profiles like mine.",
             title="My stats")
def get_stats() -> dict:
    final, page = _get("/my/stats/")
    return {"url": final, "text": _text(page)[:8000]}


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


def _cards(page: str) -> list[dict]:
    """Job cards without structured data (the dashboard): link, title, the card's text."""
    out, seen = [], set()
    for m in re.finditer(r'href="(/jobs/(\d+)-[^"/?#]+/)[^"]*"[^>]*>(.*?)</a>', page, re.S):
        if m.group(2) in seen or not clean(m.group(3)):
            continue
        seen.add(m.group(2))
        tail = re.sub(r"<script.*?</script>", "", page[m.end():m.end() + 2500], flags=re.S)
        out.append({"id": m.group(2), "url": BASE + m.group(1), "title": clean(m.group(3)),
                    "details": clean(tail)[:400]})
    return out


@server.tool("get_recommended_jobs", "Vacancies Djinni recommends for my profile (the 'Вакансії' dashboard).",
             {"description_chars": {"type": "integer", "minimum": 0, "maximum": 5000, "default": 400}},
             title="Recommended jobs")
def get_recommended_jobs(description_chars: int = 400) -> dict:
    final, page = _get("/my/dashboard/")
    jobs = _postings(page)
    for j in jobs:
        j["description"] = j["description"][:description_chars]
    jobs = jobs or _cards(page)
    return {"url": final, "count": len(jobs), "jobs": jobs}


@server.tool("get_page", "Read any djinni.co page in my session as text, e.g. /my/hires/, /my/subscriptions/, "
             "/my/stoplist/, /my/account/, /salaries/. Action links (logout, stop, kill, ?action=…) are refused.",
             {"path": {"type": "string", "description": "a djinni.co path or full https URL"},
              "links": {"type": "boolean", "default": False, "description": "also return the page's djinni.co links"},
              **PAGING}, ["path"], title="Read a Djinni page")
def get_page(path: str, links: bool = False, offset: int = 0, max_chars: int = 15000) -> dict:
    final, page = _get(path)
    out = {"url": final, "title": page_title(page), **_slice(_text(page), offset, max_chars)}
    if links:
        out["links"] = page_links(page_main(page), final, HOSTS)
    return out


# ------------------------------------------------------------------- jobs ---

@server.tool("search_jobs", "Djinni job search: ~15 vacancies per page with a short description; use get_job "
             "for the full text.",
             {"keywords": {"type": "array", "items": {"type": "string"},
                           "description": "Djinni categories (primary_keyword): JavaScript, Node.js, Fullstack…"},
              "search": {"type": "string", "description": "free text (all_keywords)"},
              "experience": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 10},
                             "description": "years buckets: 0 = no experience, 1…10"},
              "remote": {"type": "boolean", "default": False},
              "english": {"type": "string", "enum": list(ENGLISH)},
              "region": {"type": "array", "items": {"type": "string", "enum": list(REGIONS)}},
              "salary_from": {"type": "integer", "minimum": 0, "description": "USD per month"},
              "page": {"type": "integer", "minimum": 1, "default": 1},
              "description_chars": {"type": "integer", "minimum": 0, "maximum": 5000, "default": 600}},
             title="Search vacancies")
def search_jobs(keywords: list[str] | None = None, search: str | None = None, experience: list[int] | None = None,
                remote: bool = False, english: str | None = None, region: list[str] | None = None,
                salary_from: int | None = None, page: int = 1, description_chars: int = 600) -> dict:
    params = [("primary_keyword", k) for k in keywords or []]
    params += [("exp_level", "no_exp" if y == 0 else f"{y}y") for y in experience or []]
    if search:
        params.append(("all_keywords", search))
    if remote:
        params.append(("employment", "remote"))
    if english:
        params.append(("english_level", english))
    if salary_from:
        params.append(("salary", salary_from))
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


def _apply_form(page: str) -> str | None:
    form = re.search(r'<form\b[^>]*id="apply_form"[^>]*>(.*?)</form>', page, re.S)
    return form.group(1) if form else None


@server.tool("get_job", "Full text of one Djinni vacancy, plus whether I can still apply (or the thread if I "
             "already did), the CVs I can attach and my profile salary.",
             {"url": {"type": "string", "description": "https://djinni.co/jobs/<id>-<slug>/ (as search_jobs returns)"}},
             ["url"], title="Vacancy")
def get_job(url: str) -> dict:
    final, page = _get(_job_url(url))
    jobs = _postings(page)
    out = jobs[0] if jobs else {"text": _text(page)[:20000]}
    form = _apply_form(page)
    thread = re.search(r'href="/my/inbox/(\d+)/', page)
    out.update({"url": final, "can_apply": bool(form),
                "thread": thread.group(1) if thread and not form else None,
                "cvs": _cvs(form) if form else None, "profile_salary": _profile_salary(form) if form else None})
    return out


def _cvs(form: str) -> list[dict] | None:
    """My uploaded CVs offered by the apply form (the select options with an id), the preselected one marked."""
    field = parse_form(form)["fields"].get("cv_file_upload_id") or {}
    dates = {attr(a, "value"): attr(a, "data-cv-date") for a in re.findall(r"<option\b([^>]*)>", form, re.I)}
    cvs = [{"id": o["value"], "file": o["label"], "date": dates.get(o["value"]),
            "preselected": o["value"] == field.get("value")} for o in field.get("options", []) if o["value"]]
    return cvs or None


def _profile_salary(form: str) -> int | None:
    tag = re.search(r'<input\b[^>]*name="salary_changed"[^>]*>', form)
    value = attr(tag.group(0), "data-value") if tag else None
    return int(value) if value and value.isdigit() else None


# ------------------------------------------------------------ write tools ---

@server.tool("update_profile", "Change fields of my Djinni profile (names from get_profile; lists for multi-choice "
             "fields, true/false for single checkboxes). Every other field keeps its current value.",
             {"changes": {"type": "object", "description": 'e.g. {"position": "Full Stack Engineer", "salary_min": "2500"}'},
              **DRY_RUN}, ["changes"], title="Edit my profile", read_only=False, destructive=True, idempotent=True)
def update_profile(changes: dict, dry_run: bool = False) -> dict:
    if not changes:
        raise Stop("nothing to change")
    final, parsed, page = _profile_form()
    pairs = override_form(parsed["pairs"], parsed["fields"], changes)
    before = {k: parsed["fields"][k].get("value") for k in changes}
    if dry_run:
        return {"dry_run": True, "url": final, "before": before, "after": changes}
    if not any(n == "csrfmiddlewaretoken" for n, _ in pairs):
        pairs.append(("csrfmiddlewaretoken", _csrf(page)))
    _, status, body = session.request(f"{BASE}/my/profile/", data=pairs,
                                      headers={"Referer": f"{BASE}/my/profile/", "Origin": BASE})
    if status >= 400:
        raise Stop(f"HTTP {status} saving the profile")
    errors = [clean(e) for e in re.findall(r'class="[^"]*(?:invalid-feedback d-block|errorlist)[^"]*"[^>]*>(.*?)</',
                                           body, re.S) if clean(e)]
    _, after, _ = _profile_form()
    now = {k: after["fields"].get(k, {}).get("value") for k in changes}
    return {"saved": not errors, "errors": errors or None, "before": before, "now": now}


def _message_ids(page: str) -> list[str]:
    return re.findall(r'<div\s+id="msg_(\d+)"\s+class="thread-message', page)


@server.tool("send_message", "Reply in an inbox thread (to a recruiter's offer or after my application).",
             {"thread": {"type": "string", "description": "id from list_threads"},
              "text": {"type": "string"}, **DRY_RUN}, ["thread", "text"], title="Send a message",
             read_only=False, destructive=False, idempotent=False)
def send_message(thread: str, text: str, dry_run: bool = False) -> dict:
    tid = _thread_id(thread)
    if not text.strip():
        raise Stop("empty message")
    final, page = _get(f"/my/inbox/{tid}/")
    if "js-inbox-reply-form" not in page:
        raise Stop("this thread has no reply form (closed or archived)")
    payload = {"thread": tid, "url": final, "text": text, "context": (_sidebar(page) or "")[:300] or None}
    if dry_run:
        return {"dry_run": True, "would_send": payload}
    before = _message_ids(page)
    token = _csrf(page)
    _, status, _ = session.request(final, data=[("csrfmiddlewaretoken", token), ("message", text)],
                                   headers={"Referer": final, "Origin": BASE, "X-CSRFToken": token,
                                            "HX-Request": "true"})
    if status >= 400:
        raise Stop(f"HTTP {status} sending the message")
    _, page = _get(f"/my/inbox/{tid}/")
    new = [i for i in _message_ids(page) if i not in before]
    return {"sent": bool(new), "message_id": new[-1] if new else None,
            "note": None if new else "no new message in the thread — check get_thread before retrying"}


@server.tool("apply_to_job", "Apply to a Djinni vacancy as me: a message (cover letter), which of my uploaded CVs "
             "to attach (default: the one Djinni preselects; '' = none) and optionally a salary expectation for "
             "this vacancy only. Refuses if I already applied.",
             {"url": {"type": "string", "description": "https://djinni.co/jobs/<id>-<slug>/"},
              "message": {"type": "string"},
              "cv_id": {"type": "string", "description": "id from get_job.cvs; '' to send no CV"},
              "salary": {"type": "integer", "minimum": 0, "description": "USD/month for this vacancy only"},
              **DRY_RUN}, ["url", "message"], title="Apply to a vacancy", read_only=False,
             destructive=False, idempotent=False)
def apply_to_job(url: str, message: str, cv_id: str | None = None, salary: int | None = None,
                 dry_run: bool = False) -> dict:
    final, page = _get(_job_url(url))
    form = _apply_form(page)
    if not form:
        thread = re.search(r'href="/my/inbox/(\d+)/', page)
        raise Stop("no apply form on this vacancy" + (f" — already applied (thread {thread.group(1)})" if thread else
                                                      " (closed, or applying happens elsewhere)"))
    if not message.strip():
        raise Stop("empty message")
    parsed = parse_form(form)
    changes: dict = {"message": message}
    if cv_id is not None:
        changes["cv_file_upload_id"] = cv_id
    if salary is not None:
        changes["salary_changed"] = str(salary)
    pairs = override_form(parsed["pairs"], parsed["fields"], changes)
    pairs = [(n, v) for n, v in pairs if n not in ("save_msg_template", "msg_template_name")]
    cv_sent = dict(pairs).get("cv_file_upload_id")
    cv_name = next((o["label"] for o in parsed["fields"].get("cv_file_upload_id", {}).get("options", [])
                    if o["value"] == cv_sent), None)
    job = (_postings(page) or [{}])[0]
    payload = {"vacancy": job.get("title"), "company": job.get("company"), "url": final, "message": message,
               "cv": cv_name if cv_sent else None, "salary_for_this_vacancy": dict(pairs).get("salary_changed") or None,
               "profile_salary": _profile_salary(form)}
    if dry_run:
        return {"dry_run": True, "would_send": payload}
    pairs.append(("job_apply", ""))
    _, status, _ = session.request(final, data=pairs, headers={"Referer": final, "Origin": BASE})
    if status >= 400:
        raise Stop(f"HTTP {status} sending the application")
    _, page = _get(final)
    applied = _apply_form(page) is None
    return {"applied": applied, **payload,
            "note": None if applied else "the vacancy still shows the apply form — check list_threads(bucket='apply')"}


@server.tool("decline_offer", "Decline a recruiter's offer: Djinni archives the thread and tells the recruiter "
             "I'm not interested.",
             {"thread": {"type": "string", "description": "id from list_threads"}, **DRY_RUN}, ["thread"],
             title="Decline an offer", read_only=False, destructive=True, idempotent=True)
def decline_offer(thread: str, dry_run: bool = False) -> dict:
    tid = _thread_id(thread)
    final, page = _get(f"/my/inbox/{tid}/")
    payload = {"thread": tid, "url": final, "context": (_sidebar(page) or "")[:300] or None}
    if dry_run:
        return {"dry_run": True, "would_decline": payload}
    _, status, _ = session.request(f"{BASE}/htmx/htmx_archive/", data={"mt_id": tid},
                                   headers={"Referer": f"{BASE}/my/inbox/", "Origin": BASE,
                                            "X-CSRFToken": _csrf(page), "HX-Request": "true"})
    if status >= 400:
        raise Stop(f"HTTP {status} declining")
    _, arch = _get("/my/inbox/?bucket=archive")
    return {"declined": f'"mt-{tid}"' in arch, **payload}


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
