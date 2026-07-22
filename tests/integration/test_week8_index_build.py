import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.indexing.index_manifest import build_manifest  # noqa: E402
from pipelines.indexing.reporting import write_index_build_outputs  # noqa: E402


def test_week8_index_report_outputs(tmp_path: Path):
    manifest = build_manifest(
        index_release_id="index-week08-dev",
        data_release_id="data-week08-dev",
        chunk_strategy_version="section_aware_v1",
        embedding_model="dry_run",
        embedding_dim=1536,
        provider="dry_run",
        source_table="knowledge_section",
        total_chunks=3,
        embedded_chunks=0,
        skipped_chunks=3,
        error_count=0,
        warnings=["dry_run=true; embeddings were not generated"],
        elapsed_sec=0.01,
    )

    md_path, json_path = write_index_build_outputs(manifest, tmp_path)

    assert md_path.exists()
    assert json_path.exists()
    assert "index-week08-dev" in md_path.read_text()
    assert '"quality_gate": "warn"' in json_path.read_text()


def test_week8_index_report_treats_current_release_reuse_as_pass(tmp_path: Path):
    manifest = build_manifest(
        index_release_id="index-capstone-v1",
        data_release_id="data-capstone-v1",
        chunk_strategy_version="section_aware_v1",
        embedding_model="deterministic-hash-embedding-v1",
        embedding_dim=1536,
        provider="deterministic",
        source_table="knowledge_section",
        total_chunks=94,
        embedded_chunks=0,
        skipped_chunks=94,
        error_count=0,
        warnings=[],
        elapsed_sec=0.01,
    )

    _, json_path = write_index_build_outputs(manifest, tmp_path)

    assert manifest.quality_gate == "pass"
    assert "reused 94 chunks" in manifest.notes
    assert '"quality_gate": "pass"' in json_path.read_text()
