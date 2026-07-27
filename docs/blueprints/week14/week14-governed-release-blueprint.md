# Week14 Governed Release Blueprint

## Goal

Week14 turns the version fields accumulated in Week02-13 into an executable release control plane.
The deployable unit is not one container and not one prompt. It is one immutable manifest binding:

1. lakeFS data ref and Iceberg snapshots;
2. vector/lexical index release;
3. prompt templates;
4. pinned model snapshot and system card;
5. Skill Pack release;
6. GraphRAG release;
7. Week11 eval evidence and Week12 business SLO;
8. staged rollout and red-line policy.

## File-level architecture

![Week14 治理发布控制面文件级执行链](../../assets/week14/week14-governed-release-control-plane.png)

The diagram is the reading order for the code: spec input, manifest generation, impact analysis,
canary decision, registry pointer, rollback/audit and compliance evidence.

## File-level path

```text
release/specs/week14_local.yaml
  -> release/generator.py
  -> contracts/release/release_manifest_v2.schema.json
  -> release/integrity.py + release/policy.py
  -> tools/impact_analysis.py
  -> release/registry.py -> governed_release_manifest
                         -> release_environment_pointer
                         -> release_audit_event
  -> rollout/canary.py -> release_rollout_event
  -> rollout/rollback.py -> atomic pointer switch
  -> release/compliance/generator.py -> evidence pack + whitepaper
  -> governance/openlineage.py -> six inputs + one governed release output
```

## Why a release pointer

Trying to update data, index, prompt, model, skills and graph independently creates a partial-release
window. Week14 instead publishes an immutable manifest, then atomically changes one environment
pointer to that manifest. Services resolve all component IDs from the same pointer generation. A
rollback changes the pointer to the direct previous manifest; no release evidence is deleted.

## Compatibility boundary

- `contracts/release/release_manifest_schema.json` remains the Week01-13 v1 compatibility contract.
- v2 is a new governed contract; no existing table, API response or lesson command is renamed.
- `release_manifest` remains available for old exercises. New promotions use
  `governed_release_manifest` and `release_environment_pointer`.
- lakeFS is the data branch/commit/tag layer; Iceberg remains the table snapshot/schema/time-travel
  layer. Neither replaces the other.

## Production boundaries

- Student Core uses HMAC signing to demonstrate tamper detection. Production should use an external
  KMS/Sigstore signing adapter and store keys outside the repository.
- The checked-in lakeFS file defines policy, not credentials. Production deploys lakeFS separately
  with HA PostgreSQL, object storage, TLS, SSO/RBAC, backup and secret management.
- A canary decision only consumes measured metrics. Missing safety/red-line metrics cause rollback;
  an incomplete observation window causes hold.
- Canary decisions are schema-validated, release-bound and recorded in stage order. Production
  pointer promotion requires the latest 5%, 25%, 50% and 100% decisions all to be `promote`.
- Compliance generation hashes evidence that exists. It never invents missing reports.
