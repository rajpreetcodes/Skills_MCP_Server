"""Unit and integration tests for fail-closed HTTP auth, search near-ties, and correction logging."""
import json
import logging
import pytest
import tempfile
from pathlib import Path
from starlette.testclient import TestClient

from src.http_server import SkillsHTTPServer
from src.registry import SkillRegistry
from src.profile_loader import ProfileLoader
from src.tools import SkillsTools
from src.server import load_config


@pytest.fixture
def test_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        skill_root = root / "skills"
        profile_dir = root / "profiles"
        skill_root.mkdir()
        profile_dir.mkdir()

        # Skill 1: python backend
        s1 = skill_root / "python-backend"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("""---
name: python-backend
description: Fast API backend development in Python
category: backend
tags: [python, fastapi, backend]
---
# Python Backend
Python instructions.
""")

        # Skill 2: python frontend / scripting (close score on 'python' query)
        s2 = skill_root / "python-scripting"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("""---
name: python-scripting
description: Automation scripting in Python
category: automation
tags: [python, scripting]
---
# Python Scripting
Scripting instructions.
""")

        # Skill 3: rust systems (unrelated to python)
        s3 = skill_root / "rust-systems"
        s3.mkdir()
        (s3 / "SKILL.md").write_text("""---
name: rust-systems
description: Systems programming in Rust
category: systems
tags: [rust, memory-safety]
---
# Rust Systems
Rust instructions.
""")

        registry = SkillRegistry(skill_root)
        profile_loader = ProfileLoader(profile_dir, registry)
        tools = SkillsTools(registry, profile_loader)

        yield {
            "root": root,
            "skill_root": skill_root,
            "profile_dir": profile_dir,
            "registry": registry,
            "profile_loader": profile_loader,
            "tools": tools
        }


def test_http_auth_fail_closed_without_token(test_setup):
    """HTTP transport without auth_token and without no_auth must refuse to start."""
    config = {
        "skill_root": str(test_setup["skill_root"]),
        "profile_dir": str(test_setup["profile_dir"]),
        "transport": "http",
        "auth_token": None,
        "no_auth": False
    }
    with pytest.raises(ValueError, match="AUTH_TOKEN is required for HTTP transport"):
        SkillsHTTPServer(config)


def test_http_auth_explicit_no_auth(test_setup):
    """HTTP transport with no_auth=True starts and allows requests without credentials."""
    config = {
        "skill_root": str(test_setup["skill_root"]),
        "profile_dir": str(test_setup["profile_dir"]),
        "transport": "http",
        "auth_token": None,
        "no_auth": True
    }
    server = SkillsHTTPServer(config)
    client = TestClient(server.app)

    # Health check works
    r_health = client.get("/health")
    assert r_health.status_code == 200

    # Protected endpoint is accessible without credentials when no_auth=True
    r_stats = client.get("/stats")
    assert r_stats.status_code == 200
    assert r_stats.json()["skills"] == 3


def test_http_auth_with_valid_and_invalid_tokens(test_setup):
    """HTTP transport with auth_token enforces 401 on missing and 403 on invalid token."""
    config = {
        "skill_root": str(test_setup["skill_root"]),
        "profile_dir": str(test_setup["profile_dir"]),
        "transport": "http",
        "auth_token": "valid-secret-token",
        "no_auth": False
    }
    server = SkillsHTTPServer(config)
    client = TestClient(server.app)

    # Missing token -> 401
    r_missing = client.get("/stats")
    assert r_missing.status_code == 401

    # Invalid token -> 403
    r_invalid = client.get("/stats", headers={"Authorization": "Bearer wrong-token"})
    assert r_invalid.status_code == 403

    # Valid token -> 200
    r_valid = client.get("/stats", headers={"Authorization": "Bearer valid-secret-token"})
    assert r_valid.status_code == 200


@pytest.mark.asyncio
async def test_search_near_tie_flagging(test_setup):
    """Near-tied search results (margin <= 2.0) must be flagged as ambiguous."""
    tools = test_setup["tools"]

    # Both python-backend and python-scripting match 'python' in name, description, tags
    search_res = await tools._search_skills({"query": "python"})
    assert len(search_res) == 1
    data = json.loads(search_res[0].text)

    assert data["total_matches"] >= 2
    top_score = data["results"][0]["score"]
    second_score = data["results"][1]["score"]
    diff = abs(top_score - second_score)

    if diff <= 2.0:
        assert data["near_tie"] is True
        assert data["is_ambiguous"] is True
        assert "ambiguity_notice" in data
    else:
        assert data["near_tie"] is False
        assert data["is_ambiguous"] is False


@pytest.mark.asyncio
async def test_search_separated_ranking(test_setup):
    """Clearly separated search query should not be marked as a near-tie."""
    tools = test_setup["tools"]

    # Query targeting rust-specific tags and name
    search_res = await tools._search_skills({"query": "rust memory-safety"})
    assert len(search_res) == 1
    data = json.loads(search_res[0].text)

    assert data["total_matches"] == 1
    assert data["near_tie"] is False
    assert data["is_ambiguous"] is False


@pytest.mark.asyncio
async def test_search_correction_logging(test_setup, caplog):
    """When get_skill retrieves a skill other than the top search pick, a correction is logged."""
    tools = test_setup["tools"]

    # First search for 'python'
    search_res = await tools._search_skills({"query": "python"})
    data = json.loads(search_res[0].text)
    top_pick_id = data["results"][0]["skill_id"]
    second_pick_id = data["results"][1]["skill_id"]

    # Target the second pick instead of the top pick
    with caplog.at_level(logging.WARNING):
        get_res = await tools._get_skill({"skill_id": second_pick_id})
        assert isinstance(get_res, list)

    assert len(tools.correction_log) == 1
    log_entry = tools.correction_log[0]
    assert log_entry["query"] == "python"
    assert log_entry["top_pick"] == top_pick_id
    assert log_entry["actual_pick"] == second_pick_id


def test_load_config_no_auth(monkeypatch):
    """Test load_config handles NO_AUTH environment variable."""
    monkeypatch.setenv("NO_AUTH", "true")
    cfg = load_config()
    assert cfg["no_auth"] is True

    monkeypatch.setenv("NO_AUTH", "false")
    cfg2 = load_config()
    assert cfg2["no_auth"] is False
