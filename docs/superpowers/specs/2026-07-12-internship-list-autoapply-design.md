# Summer 2027 Internship List + Auto-Apply — Design

**Date:** 2026-07-12
**Status:** Approved
**Repo:** https://github.com/ArnavBagmar/2027techAutoApply

## 1. Overview

A public GitHub repo with two halves that share one data file:

1. **The list.** Every hour, a GitHub Actions workflow discovers Summer 2027 tech
   internship postings, updates `data/listings.json`, and regenerates the listings
   tables in `README.md` with direct apply links.
2. **The tool.** Anyone can clone the repo and run a Python CLI (`autoapply`) that
   reads the same `listings.json`, opens each posting in a real browser, auto-fills
   the application form from a local profile, and pauses for the human to review
   and click submit.

### Goals

- README always shows a fresh, deduplicated, categorized list of Summer 2027
  internships with apply links; new postings surface within ~1 hour of appearing.
- A cloner can go from `git clone` to filling their first application in under
  10 minutes.
- Zero hosting cost: everything runs on free GitHub Actions.
- Safe to publish publicly: the apply tool never submits on the user's behalf and
  never bypasses anti-bot measures.

### Non-goals

- Fully automated (no-human) application submission.
- CAPTCHA solving or anti-bot circumvention of any kind.
- Coverage of non-tech roles, or a primary focus on non-US postings.
- A web frontend or database; the repo itself is the product.

### Decisions made during brainstorming

| Decision | Choice |
|---|---|
| Discovery sources | Public ATS APIs (Greenhouse, Lever, Ashby, SmartRecruiters; Workday later) for a curated company list, merged with community-maintained internship list repos |
| Auto-apply behavior | Semi-automated: fill forms, human reviews and submits |
| Role/region scope | SWE + adjacent (Data/ML, Quant, Hardware/Embedded), US-focused |
| Architecture | Single repo, GitHub Actions hourly cron (Option A) |

## 2. Repo layout

```
2027techAutoApply/
├── README.md                     # project intro + auto-generated listings tables
├── ARCHIVED.md                   # auto-generated closed/expired listings
├── DISCLAIMER.md                 # usage policy for the auto-apply tool
├── CONTRIBUTING.md               # how to add companies / report bad listings
├── pyproject.toml                # one installable project, two packages
├── data/
│   ├── companies.yaml            # curated company → ATS board mapping (human-edited)
│   └── listings.json             # source of truth, machine-updated hourly
├── scraper/
│   ├── models.py                 # pydantic models: Listing, Company, ScrapeResult
│   ├── sources/
│   │   ├── base.py               # Source protocol: fetch(company) -> list[Listing]
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── smartrecruiters.py
│   │   └── community.py          # merge from community list repos
│   ├── filters.py                # intern/2027/US matching, role categorization
│   ├── merge.py                  # dedupe, diff vs previous listings, mark closed
│   ├── render.py                 # listings.json -> README/ARCHIVED markdown
│   └── main.py                   # orchestrates one scrape run
├── autoapply/
│   ├── cli.py                    # `autoapply init` / `run` / `status`
│   ├── profile.py                # load + validate profile.yaml
│   ├── state.py                  # applied.json read/write (gitignored)
│   ├── browser.py                # Playwright session management
│   └── adapters/
│       ├── base.py               # Adapter protocol: matches(url), fill(page, profile)
│       ├── greenhouse.py
│       ├── lever.py
│       └── ashby.py
├── tests/                        # pytest, fixtures per ATS
└── .github/workflows/
    ├── update-listings.yml       # hourly cron: scrape → render → commit
    └── ci.yml                    # lint + tests + coverage on PR/push
```

Files stay small and single-purpose (one source or adapter per file) per the
one-file-one-job rule; nothing should approach 400 lines.

## 3. Data pipeline (scraper)

### Sources

Each source implements `fetch() -> list[Listing]` and knows nothing about the others.

- **Greenhouse:** `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- **Lever:** `GET https://api.lever.co/v0/postings/{company}?mode=json`
- **Ashby:** `GET https://api.ashbyhq.com/posting-api/job-board/{org}`
- **SmartRecruiters:** `GET https://api.smartrecruiters.com/v1/companies/{company}/postings`
- **Workday (phase 2):** unofficial `POST …/wday/cxs/{tenant}/{site}/jobs` endpoint;
  brittle, so it lands after the four official APIs are stable.
- **Community lists:** parse the machine-readable listing files maintained by
  community internship repos (e.g. the SimplifyJobs-style `listings.json`).
  Exact repo names/paths are confirmed at implementation time and kept in a
  config constant. Community entries are tagged with `source: "community:<repo>"`
  and their apply links are used as-is.

`data/companies.yaml` maps each curated company to its ATS and board token:

```yaml
- name: Stripe
  ats: greenhouse
  board: stripe
  category_hint: swe
```

### Filtering (`filters.py`)

Pure functions over fetched postings:

1. **Internship match:** title matches intern patterns (`intern`, `internship`,
   `co-op`) and not exclusions (`internal`, `international` as standalone words).
2. **Season match:** title or description matches `2027` with `summer` proximity,
   OR posting is undated-but-intern from a company whose postings are known to be
   season-agnostic (flagged per-company in `companies.yaml`).
3. **Region:** US location strings or `Remote (US)`; postings with no parseable
   location are kept but tagged `location: "Unknown"` rather than dropped.
4. **Categorization:** keyword rules map titles to one of
   `swe | data-ml | quant | hardware`; unmatched titles default to `swe`.

### Merge and diff (`merge.py`)

- **Dedupe key:** canonical apply URL (tracking params stripped); fallback key is
  `(normalized company, normalized title, location)`.
- **Diff vs previous `listings.json`:** new postings get `first_seen` (UTC ISO
  timestamp); existing ones keep theirs; postings missing from their source get
  `active: false` + `closed_at` instead of being deleted (so users' applied-state
  and the archive stay meaningful).
- All merge operations build new lists/objects; nothing mutates prior state.

### Listing schema (pydantic, serialized to `listings.json`)

```json
{
  "id": "sha1 of dedupe key",
  "company": "Stripe",
  "title": "Software Engineering Intern, Summer 2027",
  "category": "swe",
  "locations": ["San Francisco, CA", "New York, NY"],
  "url": "https://boards.greenhouse.io/stripe/jobs/123",
  "ats": "greenhouse",
  "source": "greenhouse:stripe",
  "first_seen": "2026-07-12T17:00:00Z",
  "active": true,
  "closed_at": null
}
```

`listings.json` is written with sorted keys and stable ordering so diffs are
readable and no-change runs produce byte-identical output (→ no empty commits).

## 4. README generation (`render.py`)

A pure function `render(listings) -> (readme_section, archived_md)`:

- README has a static hand-written top (project intro, auto-apply quickstart,
  badges, last-updated timestamp) and a generated block between
  `<!-- LISTINGS:START -->` / `<!-- LISTINGS:END -->` markers.
- Tables grouped by category, newest `first_seen` first:
  `| Company | Role | Location | Posted | Apply |` — 🆕 prefix when
  `first_seen` < 24h ago, apply link as a button-style link.
- Inactive listings render into `ARCHIVED.md` (README stays well under GitHub's
  ~500 KB render limit; if the active table itself ever nears the limit, oldest
  rows spill to `ARCHIVED.md` too).

## 5. GitHub Actions workflows

### `update-listings.yml`

- `on: schedule: cron "0 * * * *"` plus `workflow_dispatch` for manual runs.
  (GitHub may delay cron runs 10–30 min under load — acceptable.)
- `permissions: contents: write`; `concurrency: update-listings` with
  `cancel-in-progress: false` so runs never overlap.
- Steps: checkout → setup Python (cached pip) → `python -m scraper.main` →
  commit `data/listings.json`, `README.md`, `ARCHIVED.md` only if `git status`
  shows changes, with message `chore: update listings YYYY-MM-DD HH:MM UTC`.
- No secrets required — all APIs are public and commits use the built-in
  `GITHUB_TOKEN`.

### `ci.yml`

Runs on PRs and pushes to `main`: ruff lint + format check, pytest with
coverage, fail under 80%.

## 6. Auto-apply CLI

### User flow

```
git clone https://github.com/ArnavBagmar/2027techAutoApply
cd 2027techAutoApply && pip install -e . && playwright install chromium
autoapply init      # interactive: builds profile.yaml, points at resume PDF
autoapply run       # iterate new listings: open → fill → human reviews → submit
autoapply status    # table of applied/skipped/pending from applied.json
```

### Components

- **`profile.py`:** loads `profile.yaml` (name, email, phone, education, work
  authorization, links, resume path, default answers like "how did you hear
  about us"); pydantic-validated with actionable error messages; the file and
  resume are gitignored and never leave the user's machine.
- **`state.py`:** `applied.json` (gitignored) records per-listing status:
  `pending | filled | submitted | skipped`, with timestamps. `run` filters out
  anything not `pending`. Users mark a listing `submitted` by confirming in the
  CLI after they click submit, or `skipped` to pass.
- **`browser.py`:** one headed Chromium via Playwright with a persistent user
  profile dir, so logins/cookies survive across runs and the user watches every
  action.
- **`adapters/`:** each adapter declares `matches(url)` and
  `fill(page, profile, listing)`. Filling uses ATS-specific selectors first,
  label-text heuristics second. Fields it can't confidently map (custom essay
  questions, dropdowns without obvious answers) are left blank and reported in
  the terminal so the human handles them during review. Unsupported ATS → the
  listing is opened for fully manual application and the CLI says so.

### Hard policies (also stated in DISCLAIMER.md)

- The tool **never clicks submit** — the human always does.
- It **never** solves, bypasses, or automates around CAPTCHAs or anti-bot checks.
- One application at a time, human-paced by design; no parallel sessions.
- Users are responsible for reviewing every application before submitting and
  for complying with each site's terms of service.

## 7. Error handling

- **Scraper:** each source runs in its own try/except; a failing source logs a
  structured warning and contributes zero listings, never aborting the run.
  If more than 50% of sources fail, the run aborts **without committing** so a
  transient outage can't mass-close listings. A per-run summary (sources OK/
  failed, new/closed counts) is written to the Actions job summary.
- **Renderer/merge:** pydantic validation on load of the previous
  `listings.json`; a corrupt file fails loudly rather than silently rebuilding
  from scratch.
- **CLI:** every user-facing failure (missing profile field, resume not found,
  unsupported ATS, page timeout) produces a plain-English message and a next
  step; stack traces only with `--verbose`.

## 8. Testing

- **Unit:** fixture JSON per ATS source (recorded real responses, anonymized) →
  parser output assertions; filter/categorization table-driven tests; merge/diff
  tests (new, unchanged, closed, revived listing cases); renderer golden-file
  test.
- **Adapter logic:** field-mapping heuristics tested against saved form HTML
  fixtures (Playwright not required in CI for these; selector logic is factored
  to be testable without a browser).
- **Integration:** one live smoke test per ATS API, marked `@pytest.mark.live`,
  excluded from CI, run manually before releases.
- **E2E (manual, documented):** checklist for `autoapply run` against one real
  Greenhouse/Lever/Ashby posting each.
- Coverage gate: 80% in CI.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| GitHub cron delays/skips | Acceptable for a job list; `workflow_dispatch` for manual refresh |
| ATS API shape changes | Per-source isolation + fixtures make breakage visible and local |
| Community repo renames/moves its data file | Source is config-driven; failure of that one source doesn't stop the run |
| Hourly commits bloat history | Commit only on change; single data file keeps deltas small |
| Auto-fill puts wrong data in a field | Human review gate before every submit; unmapped fields left blank and flagged |
| Public repo used for spammy mass-applying | No auto-submit, no CAPTCHA handling, one-at-a-time pacing, explicit disclaimer |

## 10. Future work (explicitly out of scope now)

Workday source adapter; per-user filtering config for the CLI (target companies/
categories); a `posted within` filter flag; GitHub Pages view of the list;
resume tailoring integrations.
