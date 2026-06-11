# Week04 Iceberg Baseline Report

generated_at: `2026-06-10T08:13:51.664625+00:00`

| table | rows | snapshots | files | avg file size | latest operation |
|---|---:|---:|---:|---:|---|
| bronze.raw_ticket_event | 500 | 17 | 1 | 81382.0 | append |
| bronze.raw_doc_asset | 1 | 15 | 1 | 6242.0 | append |
| silver.ticket_fact | 500 | 11 | 1 | 28443.0 | append |
| silver.knowledge_doc | 1 | 15 | 1 | 6671.0 | append |

## Known Limits

- Week04 records current table health and metadata shape; it does not run compaction.
- Partition distribution is omitted for unpartitioned Student Core Pack tables.

## Next Steps

- Use this report as the before/after baseline for Week05 transform and Week06 orchestration.
- Only introduce maintenance jobs after table growth justifies them.
