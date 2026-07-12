import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import ValidationError

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


def load_listings_or_exit(path: Path) -> list[Listing] | int:
    """Load listings, returning the list on success or an exit code on failure."""
    if not path.exists():
        print(
            f"Error: {path} not found. Run autoapply from the root of the cloned repo.",
            file=sys.stderr,
        )
        return 1
    try:
        return load_listings(path)
    except json.JSONDecodeError:
        print(
            f"Error: {path} is not valid JSON. It may be corrupted — try 'git pull' "
            "to fetch a fresh copy.",
            file=sys.stderr,
        )
        return 1
    except ValidationError:
        print(
            f"Error: {path} does not match the expected format. It may be corrupted "
            "or out of date — try 'git pull' to fetch a fresh copy.",
            file=sys.stderr,
        )
        return 1


def load_state_or_exit(path: Path) -> dict | int:
    """Load application state, returning the dict on success or an exit code on failure."""
    try:
        return load_state(path)
    except json.JSONDecodeError:
        print(
            f"Error: {path} appears corrupted (invalid JSON). "
            f"Rename it aside (e.g. 'mv {path} {path}.bak') and try again.",
            file=sys.stderr,
        )
        return 1
    except ValidationError:
        print(
            f"Error: {path} appears corrupted (unexpected contents). "
            f"Rename it aside (e.g. 'mv {path} {path}.bak') and try again.",
            file=sys.stderr,
        )
        return 1


def format_status(listings: list[Listing], state) -> str:
    counts = {"pending": 0, "filled": 0, "submitted": 0, "skipped": 0}
    for listing in listings:
        record = state.get(listing.id)
        status = record.status if record else "pending"
        if not listing.active and status == "pending":
            continue
        counts[status] += 1
    return "\n".join(f"{status}: {count}" for status, count in counts.items())


def prompt_grad_year() -> int:
    while True:
        raw = input("  Graduation year: ").strip()
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a valid year (e.g. 2027).")


def cmd_init() -> int:
    if PROFILE_PATH.exists():
        answer = input(f"{PROFILE_PATH} already exists. Overwrite? [y/n]: ").strip().lower()
        if answer != "y":
            return 0
    answers = {}
    print("Setting up your profile (saved to gitignored profile.yaml):")
    for key, prompt in INIT_FIELDS:
        answers[key] = input(f"  {prompt}: ").strip()
    answers["education"] = {
        "school": input("  School: ").strip(),
        "degree": input("  Degree (e.g. BS): ").strip(),
        "major": input("  Major: ").strip(),
        "grad_year": prompt_grad_year(),
    }
    answers["work_authorized_us"] = input("  US work authorized? [y/n]: ").lower() == "y"
    answers["needs_sponsorship"] = input("  Need sponsorship? [y/n]: ").lower() == "y"
    answers["default_answers"] = {"how_did_you_hear": "GitHub"}
    PROFILE_PATH.write_text(yaml.safe_dump(answers, sort_keys=False))
    print(f"Wrote {PROFILE_PATH}. Verify it, then run: autoapply run")
    return 0


def prompt_submitted_choice() -> str:
    while True:
        choice = input("  [s]ubmitted / s[k]ip / [q]uit: ").strip().lower()
        if choice in ("s", "k", "q"):
            return choice
        print("  Please answer s, k, or q.")


def prompt_goto_failure_choice(url: str, error: Exception) -> str:
    while True:
        choice = (
            input(f"  Could not load {url}: {error}. Marking as skipped? [k]skip / [q]uit: ")
            .strip()
            .lower()
        )
        if choice in ("k", "q"):
            return choice
        print("  Please answer k or q.")


def cmd_run() -> int:
    from autoapply.browser import apply_actions, session  # import here: needs playwright

    try:
        profile = load_profile(PROFILE_PATH)
    except ProfileError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    listings = load_listings_or_exit(LISTINGS_PATH)
    if isinstance(listings, int):
        return listings
    state = load_state_or_exit(STATE_PATH)
    if isinstance(state, int):
        return state
    todo = select_pending(listings, state)
    print(f"{len(todo)} pending applications. One at a time; YOU click submit.")

    with session(BROWSER_DIR) as context:
        page = context.new_page()
        for listing in todo:
            print(f"\n→ {listing.company}: {listing.title}\n  {listing.url}")
            try:
                page.goto(listing.url)
            except Exception as error:
                goto_choice = prompt_goto_failure_choice(listing.url, error)
                now = datetime.now(timezone.utc)
                if goto_choice == "k":
                    state = with_status(state, listing.id, "skipped", now)
                    save_state(STATE_PATH, state)
                    continue
                break

            adapter = adapter_for(page.url)
            filled = False
            if adapter is None:
                print("  Unsupported ATS — fill manually in the browser window.")
            else:
                failed = apply_actions(page, adapter.plan(profile))
                filled = True
                for action in failed:
                    print(f"  Could not fill: {action.target} — do this one by hand.")
                print("  Review EVERYTHING, answer custom questions, then submit yourself.")

            choice = prompt_submitted_choice()
            now = datetime.now(timezone.utc)
            if choice == "s":
                state = with_status(state, listing.id, "submitted", now)
            elif choice == "k":
                state = with_status(state, listing.id, "skipped", now)
            else:
                if filled:
                    state = with_status(state, listing.id, "filled", now)
                    save_state(STATE_PATH, state)
                break
            save_state(STATE_PATH, state)
    save_state(STATE_PATH, state)
    return 0


def cmd_status() -> int:
    listings = load_listings_or_exit(LISTINGS_PATH)
    if isinstance(listings, int):
        return listings
    state = load_state_or_exit(STATE_PATH)
    if isinstance(state, int):
        return state
    print(format_status(listings, state))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {"init": cmd_init, "run": cmd_run, "status": cmd_status}
    return commands[args.command]()


if __name__ == "__main__":
    sys.exit(main())
