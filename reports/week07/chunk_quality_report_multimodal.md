# Week07 Chunk Quality Report

- Parse run: `parse-run-8455249de4ad744e`
- Data release: `week07-multimodal-local-01`
- Quality status: `warn`
- Week8 ready: `true`

## Metrics

- `section_count`: 7
- `chunk_count`: 7
- `anchor_count`: 7
- `metadata_completeness`: 1.0
- `anchor_coverage`: 1.0
- `empty_chunk_count`: 0
- `unanchored_chunk_count`: 0
- `orphan_chunk_count`: 0
- `orphan_anchor_count`: 0
- `pdf_missing_page_count`: 0
- `fallback_chunk_count`: 1
- `synthetic_source_chunk_count`: 0
- `media_blocked_chunk_count`: 0
- `pii_suspected_chunk_count`: 0
- `allowed_for_indexing_count`: 7
- `gate_decision`: warn
- `completeness_score`: 1.0
- `noise_score`: 0.8571
- `evidence_score`: 1.0
- `coherence_score`: 1.0

## Warnings

- `fallback_parser_used`

## Errors

- None

## Week8 Handoff

- Week8 may index only chunks where `allowed_for_indexing=true`.
- Citations must be generated from `evidence_anchors.json` or `evidence_anchor` rows.
- Fallback parser output must not be treated as Docling-quality page/bbox evidence.
