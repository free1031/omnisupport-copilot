import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).parent.parent.parent
TOOL_API_PATH = PROJECT_ROOT / "services" / "tool_api"
SKILLS_ROOT = PROJECT_ROOT / "skills"


def _clear_app_modules():
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)


def _install_asyncpg_stub():
    if "asyncpg" in sys.modules:
        return
    asyncpg_stub = types.ModuleType("asyncpg")

    async def connect(*_args, **_kwargs):
        raise RuntimeError("asyncpg is not installed in the local skill registry test env")

    asyncpg_stub.connect = connect
    sys.modules["asyncpg"] = asyncpg_stub


def test_skill_registry_discovers_frontmatter_without_bodies():
    _clear_app_modules()
    sys.path.insert(0, str(TOOL_API_PATH))
    from app.skill_registry import SkillRegistry

    registry = SkillRegistry(SKILLS_ROOT)
    metas = registry.discover()

    names = {meta.name for meta in metas}
    assert "rag-contract-check" in names
    assert "data-contract-lint" in names
    assert all(not hasattr(meta, "body") for meta in metas)
    assert all(len(meta.digest) == 64 for meta in metas)
    assert registry.search("rag citations")[0].name == "rag-contract-check"
    _clear_app_modules()


def test_skill_registry_loads_one_skill_detail_on_demand():
    _clear_app_modules()
    sys.path.insert(0, str(TOOL_API_PATH))
    from app.skill_registry import SkillRegistry

    detail = SkillRegistry(SKILLS_ROOT).get_skill("rag-contract-check")

    assert detail.meta.name == "rag-contract-check"
    assert "RAG Contract Check" in detail.body
    assert "scripts/check_response.py" in detail.scripts
    assert "references/rag-response-contract.md" in detail.references
    assert "assets/response-fixture.json" in detail.assets
    _clear_app_modules()


def test_skill_registry_exports_openai_and_mcp_descriptors():
    _clear_app_modules()
    sys.path.insert(0, str(TOOL_API_PATH))
    from app.skill_registry import SkillRegistry, mcp_tool_exports, openai_tool_exports

    metas = SkillRegistry(SKILLS_ROOT).discover()
    openai_tools = openai_tool_exports(metas)
    mcp_tools = mcp_tool_exports(metas)

    assert any(tool["function"]["name"] == "activate_skill_rag_contract_check" for tool in openai_tools)
    assert all(tool["function"]["parameters"]["additionalProperties"] is False for tool in openai_tools)
    assert any(tool["name"] == "skills.activate.rag-contract-check" for tool in mcp_tools)
    assert all("inputSchema" in tool and "outputSchema" in tool for tool in mcp_tools)
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in mcp_tools)
    _clear_app_modules()


def test_tool_api_skill_endpoints(monkeypatch):
    _clear_app_modules()
    monkeypatch.setenv("SKILL_REGISTRY_PATH", str(SKILLS_ROOT))
    tool_api_path = str(TOOL_API_PATH)
    if tool_api_path in sys.path:
        sys.path.remove(tool_api_path)
    sys.path.insert(0, tool_api_path)
    _install_asyncpg_stub()

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    listing = client.get("/api/v1/skills")
    assert listing.status_code == 200
    listing_payload = listing.json()
    assert listing_payload["count"] == 5
    assert "progressive_disclosure" in listing_payload
    assert all("body" not in skill for skill in listing_payload["skills"])

    detail = client.get("/api/v1/skills/rag-contract-check")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["name"] == "rag-contract-check"
    assert "RAG Contract Check" in detail_payload["body"]

    openai = client.get("/api/v1/skills/exports/openai")
    assert openai.status_code == 200
    assert openai.json()["format"] == "openai_tools"

    mcp = client.get("/api/v1/skills/exports/mcp")
    assert mcp.status_code == 200
    assert mcp.json()["tools"][0]["inputSchema"]["type"] == "object"

    missing = client.get("/api/v1/skills/no-such-skill")
    assert missing.status_code == 404
    _clear_app_modules()
