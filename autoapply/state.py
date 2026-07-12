import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from scraper.models import Listing

Status = Literal["pending", "filled", "submitted", "skipped"]


class Record(BaseModel):
    listing_id: str
    status: Status
    updated_at: datetime


def load_state(path: Path) -> dict[str, Record]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {key: Record.model_validate(value) for key, value in raw.items()}


def save_state(path: Path, state: dict[str, Record]) -> None:
    payload = {key: record.model_dump(mode="json") for key, record in state.items()}
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    directory = path.parent if str(path.parent) else Path(".")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def with_status(
    state: dict[str, Record], listing_id: str, status: Status, now: datetime
) -> dict[str, Record]:
    record = Record(listing_id=listing_id, status=status, updated_at=now)
    return {**state, listing_id: record}


def select_pending(listings: list[Listing], state: dict[str, Record]) -> list[Listing]:
    def is_pending(listing: Listing) -> bool:
        record = state.get(listing.id)
        return record is None or record.status in ("pending", "filled")

    return [item for item in listings if item.active and is_pending(item)]
