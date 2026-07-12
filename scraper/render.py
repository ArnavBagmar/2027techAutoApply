from datetime import datetime, timedelta

from scraper.models import Category, Listing

CATEGORY_TITLES: dict[Category, str] = {
    "swe": "💻 Software Engineering",
    "data-ml": "📊 Data Science & ML",
    "quant": "📈 Quant & Trading",
    "hardware": "🔧 Hardware & Embedded",
}
START = "<!-- LISTINGS:START -->"
END = "<!-- LISTINGS:END -->"
NEW_WINDOW = timedelta(hours=24)
TABLE_HEADER = [
    "| Company | Role | Location | Posted | Apply |",
    "| --- | --- | --- | --- | --- |",
]


def _row(listing: Listing, marker: str) -> str:
    locations = "; ".join(listing.locations) or "Unknown"
    posted = listing.first_seen.strftime("%b %d")
    return (
        f"| {marker}{listing.company} | {listing.title} | {locations} "
        f"| {posted} | [Apply]({listing.url}) |"
    )


def render_listings(listings: list[Listing], now: datetime) -> str:
    active = [item for item in listings if item.active]
    lines = [f"_Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')} — {len(active)} open positions_"]
    for category, title in CATEGORY_TITLES.items():
        rows = sorted(
            (item for item in active if item.category == category),
            key=lambda item: item.first_seen,
            reverse=True,
        )
        if not rows:
            continue
        lines += ["", f"## {title}", ""] + TABLE_HEADER
        lines += [_row(item, "🆕 " if now - item.first_seen < NEW_WINDOW else "") for item in rows]
    return "\n".join(lines)


def render_archived(listings: list[Listing]) -> str:
    closed = sorted(
        (item for item in listings if not item.active),
        key=lambda item: item.closed_at or item.first_seen,
        reverse=True,
    )
    lines = ["# Archived listings", "", "Roles that are no longer accepting applications.", ""]
    lines += TABLE_HEADER
    lines += [_row(item, "") for item in closed]
    return "\n".join(lines) + "\n"


def inject_section(text: str, section: str) -> str:
    before, _, rest = text.partition(START)
    _, _, after = rest.partition(END)
    return f"{before}{START}\n{section}\n{END}{after}"
