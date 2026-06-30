# Week07 Chunk Quality Report

- Parse run: `parse-run-8c3dac8826a7a95b`
- Data release: `week07-local-file-demo`
- Quality status: `warn`
- Week8 ready: `false`

## Metrics

- `section_count`: 5
- `chunk_count`: 5
- `anchor_count`: 5
- `metadata_completeness`: 1.0
- `anchor_coverage`: 1.0
- `empty_chunk_count`: 0
- `unanchored_chunk_count`: 0
- `orphan_chunk_count`: 0
- `orphan_anchor_count`: 0
- `pdf_missing_page_count`: 0
- `fallback_chunk_count`: 5
- `synthetic_source_chunk_count`: 5
- `media_blocked_chunk_count`: 0
- `pii_suspected_chunk_count`: 0
- `allowed_for_indexing_count`: 0
- `gate_decision`: warn
- `completeness_score`: 1.0
- `noise_score`: 0.0
- `evidence_score`: 1.0
- `coherence_score`: 1.0

## Warnings

- `fallback_parser_used`
- `source_path_missing_synthetic_fallback`

## Errors

- None

## Week8 Handoff

- Week8 may index only chunks where `allowed_for_indexing=true`.
- Citations must be generated from `evidence_anchors.json` or `evidence_anchor` rows.
- Fallback parser output must not be treated as Docling-quality page/bbox evidence.
