from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from autoapply.adapters.base import FillAction

ACTION_TIMEOUT_MS = 3000


def apply_actions(page: Page, actions: list[FillAction]) -> list[FillAction]:
    """Apply fill actions; return the ones that failed so the human can do them."""
    failed: list[FillAction] = []
    for action in actions:
        try:
            if action.kind == "css":
                page.fill(action.target, action.value, timeout=ACTION_TIMEOUT_MS)
            elif action.kind == "label":
                page.get_by_label(action.target).first.fill(action.value, timeout=ACTION_TIMEOUT_MS)
            elif action.kind == "file_css":
                page.set_input_files(action.target, action.value, timeout=ACTION_TIMEOUT_MS)
        except Exception:
            failed.append(action)
    return failed


@contextmanager
def session(user_data_dir: Path):
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(user_data_dir), headless=False)
        try:
            yield context
        finally:
            context.close()
