# Design: Community-Listing Liveness Checks

**Date:** 2026-07-12
**Status:** Approved

## Problem

Some README listings link to dead pages ("job not found" / 404). Listings
sourced from ATS APIs (Greenhouse, Lever, Ashby, SmartRecruiters) self-heal:
when the API stops returning a job, `merge()` archives it. Listings imported
from the community source (`vanshb03/Summer2027-Internships`) do not — we
trust the upstream `active` flag, and the upstream keeps carrying jobs whose
URLs have died. Those dead links reach the README unchecked and stay there.

## Goals

- A new community listing's URL is verified live before it first appears on
  the README.
- Active community listings are rechecked every run; ones that die later are
  archived automatically.
- Never archive a live job because of a bot-block, timeout, or transient
  error (conservative verdicts).
- No new workflow, no second writer to `listings.json`/README.

## Non-Goals

- Checking ATS-API-sourced listings (already verified hourly by their APIs).
- Headless-browser verification of an Apply button.
- A PR/issue flow for contributors to submit individual listings.
- Recording an archival *reason* on listings.

## Architecture

One new module, `scraper/liveness.py`, invoked as a step inside
`scraper.main` between `merge()` and `write_outputs()`. The hourly
`update-listings.yml` workflow is unchanged.

```
fetch (ATS APIs + community) → merge → liveness step → write outputs
                                        │
                                        └─ checks active community listings only
```

## Components

### 1. Classifier — `scraper/liveness.py`

`check_url(url: str, timeout: float = 10.0) -> Verdict` where
`Verdict = Literal["alive", "dead", "unknown"]`:

| Signal | Verdict |
| --- | --- |
| HTTP 404 or 410 | `dead` |
| HTTP 200 + tombstone pattern in body | `dead` |
| HTTP 200 otherwise | `alive` |
| 403 / 429 / 5xx / timeout / connection error / any exception | `unknown` |

Tombstone patterns (case-insensitive, conservative — extend only with
verified real-world examples): "job not found", "no longer accepting
applications", "posting is no longer available", "this position has been
filled", "this job is no longer active".

**Workday special case:** `*.myworkdayjobs.com` job pages are JS-rendered —
the raw HTML is identical for live and dead jobs. The public URL
`https://<tenant>.wdN.myworkdayjobs.com/<site>/job/<path>` is translated to
Workday's JSON endpoint
`https://<tenant>.wdN.myworkdayjobs.com/wday/cxs/<tenant>/<site>/job/<path>`
and the verdict is classified from that response (404 → `dead`, 200 JSON →
`alive`, else `unknown`).

Mechanics: GET with a browser-like User-Agent, redirects followed, ~10 s
timeout, `ThreadPoolExecutor` with ~8 workers. Checking ~40 URLs adds
seconds to the hourly run.

### 2. Model — `scraper/models.py`

`Listing` gains `dead_checks: int = 0` — count of consecutive `dead`
verdicts. Serialized in `listings.json`; existing entries default to 0
(backward compatible). All updates via `model_copy` (immutable).

`DEAD_THRESHOLD = 2` lives in `scraper/liveness.py`.

### 3. Liveness step — applied after merge

For each **active community** listing (`source` starts with `community:`):

- New this run (id not in previous data): check now. `dead` → stored
  inactive with `dead_checks = DEAD_THRESHOLD` and `closed_at = now`
  (lands in ARCHIVED.md, never on the README, and is not resurrected or
  rechecked later). `alive`/`unknown` → published with `dead_checks = 0`.
- Existing: check now. `dead` → `dead_checks + 1`; when it reaches
  `DEAD_THRESHOLD` → `active = False`, `closed_at = now` (moves to
  ARCHIVED.md). `alive`/`unknown` → `dead_checks = 0`.

Inactive listings are never checked.

### 4. Merge rule change — `scraper/merge.py`

Today `merge()` resurrects any previous listing the upstream still carries
(`active=True, closed_at=None`). Because the community upstream keeps
listing dead-linked jobs, a liveness-archived listing would flap back onto
the README every hour. Two changes:

- `merge()` preserves `dead_checks` from the previous record when a fetched
  listing matches an existing id.
- A previous record with `dead_checks >= DEAD_THRESHOLD` is **never
  resurrected** — it stays archived even while the upstream still lists it.

## Reporting

The run summary in `scraper/main.py` (stdout + `GITHUB_STEP_SUMMARY`) gains
one line: `liveness: checked N, dead M, archived K`.

## Error Handling

- Every per-URL failure is a verdict (`unknown`), never an exception.
- The whole liveness step is wrapped: on total failure, log and proceed
  with listings unchanged. A broken checker can delay archiving but can
  never block the hourly publish.
- `unknown` never increments `dead_checks` and resets it to 0 — bot-blocking
  sites (Optiver, Citadel) can never drift toward archival.

## Testing

TDD with mocked HTTP (no live network in tests):

- Classifier verdict table: each status-code row, tombstone-text match on
  200, non-matching 200, exception → `unknown`.
- Workday URL → CxS endpoint translation, including multi-segment job paths.
- State transitions: `dead_checks` increment, reset on `alive`/`unknown`,
  archival at threshold.
- Ingest gate: new dead listing stored inactive at threshold; new
  alive/unknown listing published.
- Merge no-resurrect rule: previous record at threshold stays archived while
  upstream still carries the id; `dead_checks` preserved through merge.
  (Primary regression test.)
- Liveness-step wrapper: total failure leaves listings unchanged and does
  not raise.

## Rollout

Ships in the existing package; the next hourly run starts checking. Existing
`listings.json` entries deserialize with `dead_checks = 0` — dead links
already on the README are archived after two consecutive dead verdicts
(~2 hours).
