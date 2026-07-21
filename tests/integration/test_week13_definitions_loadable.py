import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
pytest.importorskip("dagster")

from pipelines.definitions import defs  # noqa: E402


def test_week13_graph_assets_are_registered_without_breaking_existing_defs():
    asset_keys = {"/".join(key.path) for key in defs.resolve_all_asset_keys()}

    assert "week13_graph_release" in asset_keys
    assert "week13_graph_build" in asset_keys
    assert "build_knowledge_index" in asset_keys
    assert "knowledge_chunks" in asset_keys
