# Auto-apply setup

## Requirements
- Python 3.11+
- Chromium (installed by the playwright step below)

## Install

```bash
git clone https://github.com/ArnavBagmar/2027techAutoApply.git
cd 2027techAutoApply
pip install -e .
playwright install chromium
```

## Configure

```bash
autoapply init          # answers are saved to gitignored profile.yaml
```

Or copy `profile.example.yaml` to `profile.yaml` and edit it. Set
`resume_path` to an absolute path to your resume PDF.

## Apply

```bash
git pull                # grab the freshest listings
autoapply run
```

For each pending listing the tool opens the posting in a visible browser,
fills what it can from your profile, and lists anything it could not fill.
Answer the custom questions, review every field, click submit yourself, then
tell the CLI: `s` (submitted), `k` (skip), or `q` (quit).

```bash
autoapply status        # pending / filled / submitted / skipped counts
```

Supported ATS for auto-fill: Greenhouse, Lever, Ashby. Anything else opens
for manual completion. Read [DISCLAIMER.md](../DISCLAIMER.md) before using.
