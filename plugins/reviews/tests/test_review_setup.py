"""The machine record prefers the reviews directory and falls back to the legacy file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins" / "reviews" / "scripts"))

import review_setup  # noqa: E402


def test_load_machine_prefers_reviews_config_and_falls_back(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = home / ".saga"
    legacy.mkdir(parents=True)
    (legacy / "machine.json").write_text(
        json.dumps({"schema": "legacy", "survey": {"sandbox": {"reproduction": "unavailable"}}}),
        encoding="utf-8",
    )
    loaded = review_setup.load_machine(home)
    assert loaded is not None
    assert loaded["schema"] == "legacy"
    assert not review_setup.machine_path(home).exists()

    record = review_setup.survey(tmp_path, home)
    assert review_setup.machine_path(home).is_file()
    assert review_setup.load_machine(home)["schema"] == review_setup.MACHINE_SCHEMA
    assert record["survey"]["tools"]
    assert json.loads((legacy / "machine.json").read_text(encoding="utf-8"))["schema"] == "legacy"
