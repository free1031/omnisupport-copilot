import json
import re
from pathlib import Path

import jsonschema
import yaml


PROJECT_ROOT = Path(__file__).parent.parent.parent
SKILLS_ROOT = PROJECT_ROOT / "skills"
SKILL_SCHEMA = PROJECT_ROOT / "contracts" / "skills" / "skill_pack.schema.json"
RELEASE_SCHEMA = PROJECT_ROOT / "contracts" / "release" / "release_manifest_schema.json"
RELEASE_EXAMPLE = PROJECT_ROOT / "contracts" / "release" / "release_manifest_example.json"

EXPECTED_SKILLS = {
    "data-contract-lint",
    "ingest-backfill-runbook",
    "rag-contract-check",
    "prompt-release",
    "release-check",
}


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match, f"{path} is missing YAML frontmatter"
    return yaml.safe_load(match.group(1))


def test_week09_skill_pack_frontmatter_matches_contract():
    schema = json.loads(SKILL_SCHEMA.read_text(encoding="utf-8"))
    found = set()
    for skill_md in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        payload = _frontmatter(skill_md)
        jsonschema.validate(payload, schema)
        assert payload["name"] == skill_md.parent.name
        assert payload["description"]
        assert payload["version"] == "0.1.0"
        assert payload["not_for"], f"{payload['name']} should include negative routing hints"
        assert payload["outputs"], f"{payload['name']} should declare output artifacts"
        found.add(payload["name"])

    assert found == EXPECTED_SKILLS


def test_week09_skill_pack_structure_has_on_demand_assets():
    for name in EXPECTED_SKILLS:
        skill_dir = SKILLS_ROOT / name
        assert (skill_dir / "SKILL.md").exists()
        assert any((skill_dir / "scripts").glob("*")), f"{name} needs a script placeholder"
        assert any((skill_dir / "references").glob("*")), f"{name} needs a reference"
        assert any((skill_dir / "assets").glob("*")), f"{name} needs an asset/template"


def test_release_manifest_accepts_skill_pack_binding():
    schema = json.loads(RELEASE_SCHEMA.read_text(encoding="utf-8"))
    example = json.loads(RELEASE_EXAMPLE.read_text(encoding="utf-8"))

    jsonschema.validate(example, schema)
    assert example["skill_release_id"] == "skills-v0.1.0"
    assert example["skills"][0]["name"] == "rag-contract-check"
    assert example["skills"][0]["version"] == "0.1.0"
