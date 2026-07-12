# Contributing

## Add a company

1. Find the company's job board: Greenhouse (`boards.greenhouse.io/<board>`),
   Lever (`jobs.lever.co/<board>`), Ashby (`jobs.ashbyhq.com/<board>`), or
   SmartRecruiters.
2. Add an entry to `data/companies.yaml`:
   ```yaml
   - name: Company Name
     ats: greenhouse
     board: boardtoken
   ```
3. Verify the token resolves, e.g.
   `curl -s "https://boards-api.greenhouse.io/v1/boards/<board>/jobs" | head -c 300`
   should return JSON, not a 404. Open a PR; CI must pass.

## Report a bad listing

Open an issue with the listing URL and what's wrong (dead link, not an
internship, wrong season/region).
