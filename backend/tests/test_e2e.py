"""Browser smoke test of the core loop. Run with `uv run just e2e` (builds the frontend)."""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        pytest.skip("frontend not built (npm run build)")
    db = tmp_path_factory.mktemp("e2e") / "e2e.db"
    env = {**os.environ, "SOMMELIER_DB": str(db), "SOMMELIER_DB_URL": ""}
    py = [sys.executable, "-m"]
    subprocess.run([*py, "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    subprocess.run(
        [*py, "sommelier", "import", "fixtures/seed.jsonl"], cwd=ROOT, env=env, check=True
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [*py, "uvicorn", "sommelier.app:app", "--port", str(port)], cwd=ROOT, env=env
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            httpx.get(f"{url}/api/health", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


def test_core_loop(server: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server)
        prompt = page.get_by_test_id("prompt")
        expect(prompt).to_be_visible()
        first = prompt.inner_text()
        # Nothing about the answer is on the page before submitting.
        expect(page.get_by_test_id("reveal")).to_have_count(0)
        page.keyboard.press("1")
        page.keyboard.press("m")
        page.keyboard.press("Enter")
        reveal = page.get_by_test_id("reveal")
        expect(reveal).to_be_visible()
        expect(reveal.get_by_text("The tell")).to_be_visible()
        page.keyboard.press("n")
        expect(page.get_by_test_id("reveal")).to_have_count(0)
        expect(prompt).not_to_have_text(first)
        page.get_by_role("button", name="Stats").click()
        expect(page.get_by_text("1 answered of 11 active items")).to_be_visible()
        browser.close()
