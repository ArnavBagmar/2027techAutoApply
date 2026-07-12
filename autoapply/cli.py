import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from autoapply.adapters.base import adapter_for
from autoapply.profile import ProfileError, load_profile
from autoapply.state import load_state, save_state, select_pending, with_status
from scraper.models import Listing

LISTINGS_PATH = Path("data/listings.json")
PROFILE_PATH = Path("profile.yaml")
STATE_PATH = Path("applied.json")
BROWSER_DIR = Path(".browser-profile")

INIT_FIELDS = [
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("linkedin", "LinkedIn URL (optional)"),
    ("github", "GitHub URL (optional)"),
    ("resume_path", "Absolute path to resume PDF"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoapply",
        description="Semi-automated internship applications. YOU review and submit each one.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create profile.yaml interactively")
    sub.add_parser("run", help="fill pending applications, one at a time")
    sub.add_parser("status", help="show application counts")
    return parser


def load_listings(path: Path) -> list[Listing]:
    return [Listing.model_validate(entry) for entry in json.loads(path.read_text())]


def format_status(listings: list[Listing], state) -> str:
    counts = {"pending": 0, "filled": 0, "submitted": 0, "skipped": 0}
    for listing in listings:
        record = state.get(listing.id)
        status = record.status if record else "pending"
        if not listing.active and status == "pending":
            continue
        counts[status] += 1
    return "\n".join(f"{status}: {count}" for status, count in counts.items())


def cmd_init() -> int:
    answers = {}
    print("Setting up your profile (saved to gitignored profile.yaml):")
    for key, prompt in INIT_FIELDS:
        answers[key] = input(f"  {prompt}: ").strip()
    answers["education"] = {
        "school": input("  School: ").strip(),
        "degree": input("  Degree (e.g. BS): ").strip(),
        "major": input("  Major: ").strip(),
        "grad_year": int(input("  Graduation year: ").strip()),
    }
    answers["work_authorized_us"] = input("  US work authorized? [y/n]: ").lower() == "y"
    answers["needs_sponsorship"] = input("  Need sponsorship? [y/n]: ").lower() == "y"
    answers["default_answers"] = {"how_did_you_hear": "GitHub"}
    PROFILE_PATH.write_text(yaml.safe_dump(answers, sort_keys=False))
    print(f"Wrote {PROFILE_PATH}. Verify it, then run: autoapply run")
    return 0


def cmd_run() -> int:
    from autoapply.browser import apply_actions, session  # import here: needs playwright

    try:
        profile = load_profile(PROFILE_PATH)
    except ProfileError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    listings = load_listings(LISTINGS_PATH)
    state = load_state(STATE_PATH)
    todo = select_pending(listings, state)
    print(f"{len(todo)} pending applications. One at a time; YOU click submit.")

    with session(BROWSER_DIR) as context:
        page = context.new_page()
        for listing in todo:
            print(f"\n→ {listing.company}: {listing.title}\n  {listing.url}")
            page.goto(listing.url)
            adapter = adapter_for(listing.url)
            if adapter is None:
                print("  Unsupported ATS — fill manually in the browser window.")
            else:
                failed = apply_actions(page, adapter.plan(profile))
                for action in failed:
                    print(f"  Could not fill: {action.target} — do this one by hand.")
                print("  Review EVERYTHING, answer custom questions, then submit yourself.")
            choice = input("  [s]ubmitted / s[k]ip / [q]uit: ").strip().lower()
            now = datetime.now(timezone.utc)
            if choice == "s":
                state = with_status(state, listing.id, "submitted", now)
            elif choice == "k":
                state = with_status(state, listing.id, "skipped", now)
            else:
                break
            save_state(STATE_PATH, state)
    save_state(STATE_PATH, state)
    return 0


def cmd_status() -> int:
    listings = load_listings(LISTINGS_PATH)
    print(format_status(listings, load_state(STATE_PATH)))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {"init": cmd_init, "run": cmd_run, "status": cmd_status}
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
