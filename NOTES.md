# Djinni behaviour notes

Things that are not obvious from the tool descriptions and cost time to find out.
Observed in November 2026 while building the job-freshness tools; Djinni's markup
and validation can change, so treat this as "verify before trusting".

## Dates: published vs updated

- JSON-LD `datePosted` is the **update** date, not the publication date. A bump
  restarts the advertisement's 30-day window: `validThrough` equals
  `datePosted + 30 days`. Verified on a vacancy posted 16 September and bumped
  23 November: `datePosted` said `2026-11-23`.
- The real pair lives in the page markup, in
  `<div id="job-publication-info">`:
  `Published 16 September · Updated 23 November` (EN) or
  `Опубліковано 16 вересня · Оновлено 23 листопада` (UK). The locale follows
  `Accept-Language`.
- That text carries **no year**, so it has to be inferred: take the current year,
  and step back one if the resulting date would be in the future.
- Consequence: search results are ordered by the update date, so an old
  advertisement that was merely bumped looks as fresh as a new one.

## Saving the profile is atomic

- The write tool posts the **whole profile form**, not a diff. One rejected field
  rejects the entire submit and **nothing is written** — the profile is untouched
  and the call can simply be retried.
- A rejected field surfaces as `field rejected: <div class="is-invalid">` with no
  name, which is useless for diagnosis. Isolate by sending one category at a time
  (e.g. only skill years, then only new skills).
- After a successful save the form re-renders and can be read back, so the tool
  verifies what landed instead of assuming it.

## Skills

- Years accept plain integers (`"3"`) and are stored as `"3.0"`. Allowed values
  are the `SKILL_YEARS` set: `"", 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7,
  8, 9, 10`.
- Skill names are normalised to Djinni's own dictionary, so the name you send may
  come back renamed: `Bash` → `Bash scripting`, `ELK` → `ELK stack`,
  `Vault` → `Hashicorp Vault`, `Pub/Sub` → `Google PubSub`,
  `LLM agents` → `LLM`, `AWS CloudWatch` → `CloudWatch`, `nginx` → `Nginx`.
- A name that is not in the dictionary invalidates the whole form. When unsure,
  add the skill through the UI autocomplete (it resolves the canonical name) and
  use the API only for edits to existing rows.
- Rows are addressed as `skills_experience[N][skill]` and
  `skills_experience[N][experience_years]`.

## Field limits and coded values

- Free-text profile fields accept **200–2500 characters**; shorter or longer is
  rejected by the form.
- `experience_years` (overall experience) is a coded select `0..16`, where `16`
  means "більше 10 років" — it is not a number of years.
- There is **no education field** on a Djinni candidate profile; do not look for
  one. Certifications are free text (name + provider). Work-experience entries
  have no dedicated tool: only profile-form fields and skill chips are editable.

## Session quirks

- A `status` call can report `logged_in: false` while the session is actually
  fine: the first `GET /my/profile/` may bounce to `/login`, the server then
  re-establishes the session from `.env`, and the next call succeeds. Do not
  "fix" the credentials on the strength of one `status` result.
- Cookies are the preferred credential. Only the cookie jar is persisted (in
  `.state/`); the password is never written to disk and never logged.

## Request budgets

Keep two budgets separate:

| Budget | Covers |
|---|---|
| session/account | everything under `/my/` |
| anonymous | public `/jobs/?...` listings and `/jobs/<id>-<slug>/` pages |

Public job pages and listings need no session at all. Routine scanning can run
anonymously, which keeps it off the account budget and never sends the cookie.
Either way: one request at a time, 3–7 s pause, and stop on 403/429/captcha
instead of retrying in a loop.

## Profile form field map

`get_profile` returns every field of `/my/profile/` with its value, label and
options. The names worth knowing:

| Field | Holds |
|---|---|
| `position` | desired position, free text |
| `salary_min`, `salary_hour` | salary numbers |
| `experience_years` | overall experience, select `0..16` |
| `moreinfo` | the long "about / work experience" text |
| `highlights` | the Highlights block |
| `looking_for` | the Looking-for block |
| `country_code`, `location` | country code (e.g. `UKR`) and free-text city/region |
| `format_options`, `employment_options` | lists, e.g. `['remote']`, `['fulltime','parttime','freelance']` |
| `domain_zones` | domains not considered, e.g. `['adult','gambling',…]` |
| `language_knowledge[i][code]`, `[level]` | languages (`eng`/`ukr`, `B2`/`native`) |
| `domain_experience[i][domain]`, `[experience_years]` | domain experience |
| `certifications[i][name]`, `[provider]` | certifications, free text |
| `skills_experience[N][skill]`, `[experience_years]` | skill chips and their years |
| `primary_keyword_cache` | keyword select with the full keyword list |
