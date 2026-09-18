"""Integration tests for the MCP server."""
import pytest
import tempfile
import json
from pathlib import Path

from src.server import SkillsMCPServer, load_config
from src.registry import SkillRegistry
from src.profile_loader import ProfileLoader


class TestMCPServer:
    """Test MCP server initialization and tool registration."""

    @pytest.fixture
    def temp_config(self):
        """Create temporary config with test skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_root = root / "skills"
            profile_dir = root / "profiles"
            skill_root.mkdir()
            profile_dir.mkdir()

            # Create a test skill
            skill_dir = skill_root / "test-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: test-skill
description: A test skill for integration testing
category: testing
tags: [test, integration]
triggers: ["test this"]
---
# Test Skill
This is a test skill for integration testing.
""")

            # Create a test profile
            (profile_dir / "test-profile.yaml").write_text("""name: test-profile
description: Test profile
skills:
  - test-skill
""")

            config = {
                "skill_root": str(skill_root),
                "profile_dir": str(profile_dir),
                "transport": "stdio",
                "host": "0.0.0.0",
                "port": 8000,
                "log_level": "DEBUG",
                "auth_token": None
            }

            config_file = root / "config.json"
            with open(config_file, 'w') as f:
                json.dump(config, f)

            yield config, config_file

    def test_server_initialization(self, temp_config):
        """Test server initializes correctly."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        assert server.registry is not None
        assert server.profile_loader is not None
        assert server.tools is not None
        assert server.resources is not None
        assert server.prompts is not None

        # Check skills loaded
        assert len(server.registry._skills) == 1
        skill = list(server.registry._skills.values())[0]
        assert skill.metadata.name == "test-skill"

        # Check profiles loaded
        assert len(server.profile_loader._profiles) == 1
        profile = server.profile_loader.get_profile("test-profile")
        assert profile is not None
        assert profile.name == "test-profile"

    def test_server_tools_registered(self, temp_config):
        """Test all MCP tools are registered."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        tools = server.tools.get_tools()
        tool_names = [t.name for t in tools]

        expected_tools = [
            "list_skills",
            "search_skills",
            "get_skill",
            "get_skills",
            "list_profiles",
            "get_profile",
            "resolve_profile",
            "refresh_skills",
            "get_categories",
            "get_skill_stats"
        ]

        for expected in expected_tools:
            assert expected in tool_names, f"Missing tool: {expected}"

        for tool in tools:
            assert tool.annotations is not None, f"Tool {tool.name} missing annotations"
            assert isinstance(tool.annotations.read_only_hint, bool), f"{tool.name} missing boolean read_only_hint"
            assert isinstance(tool.annotations.destructive_hint, bool), f"{tool.name} missing boolean destructive_hint"
            assert isinstance(tool.annotations.idempotent_hint, bool), f"{tool.name} missing boolean idempotent_hint"
            assert isinstance(tool.annotations.open_world_hint, bool), f"{tool.name} missing boolean open_world_hint"

    def test_server_resources_registered(self, temp_config):
        """Test MCP resources are registered."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        resources = server.resources.get_resources()
        resource_uris = [r.uri for r in resources]

        # Should have list and categories resources
        assert "skill://list" in resource_uris
        assert "skill://categories" in resource_uris
        # Should have skill resource
        assert any(uri.startswith("skill://test-skill") for uri in resource_uris)

    def test_server_prompts_registered(self, temp_config):
        """Test MCP prompts are registered."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        prompts = server.prompts.get_prompts()
        prompt_names = [p.name for p in prompts]

        expected_prompts = [
            "activate_skill",
            "activate_skills",
            "activate_profile",
            "suggest_skills"
        ]

        for expected in expected_prompts:
            assert expected in prompt_names, f"Missing prompt: {expected}"

    def test_load_config_from_file(self, temp_config):
        """Test loading config from file."""
        config, config_file = temp_config
        loaded = load_config(config_file)

        assert loaded["skill_root"] == config["skill_root"]
        assert loaded["profile_dir"] == config["profile_dir"]

    def test_load_config_env_override(self, temp_config, monkeypatch):
        """Test environment variable overrides config."""
        config, config_file = temp_config
        monkeypatch.setenv("SKILL_ROOT", "/custom/path")
        monkeypatch.setenv("PORT", "9000")

        loaded = load_config(config_file)
        assert loaded["skill_root"] == "/custom/path"
        assert loaded["port"] == 9000

    def test_server_stats(self, temp_config):
        """Test server statistics."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        stats = server.get_stats()
        assert stats["skills"] == 1
        assert stats["profiles"] == 1
        assert stats["categories"] >= 1

    @pytest.mark.asyncio
    async def test_tool_list_skills(self, temp_config):
        """Test list_skills tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.tools.call_tool("list_skills", {"limit": 10})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "test-skill"

    @pytest.mark.asyncio
    async def test_tool_search_skills(self, temp_config):
        """Test search_skills tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.tools.call_tool("search_skills", {"query": "test", "limit": 10})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["query"] == "test"
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "test-skill"

    @pytest.mark.asyncio
    async def test_tool_get_skill(self, temp_config):
        """Test get_skill tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        skill_id = list(server.registry._skills.keys())[0]
        result = await server.tools.call_tool("get_skill", {"skill_id": skill_id})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["metadata"]["name"] == "test-skill"
        assert "content" in data
        assert "Test Skill" in data["content"]

    @pytest.mark.asyncio
    async def test_tool_get_skills_batch(self, temp_config):
        """Test get_skills batch tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        skill_ids = list(server.registry._skills.keys())
        result = await server.tools.call_tool("get_skills", {"skill_ids": skill_ids})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["found"] == 1
        assert len(data["skills"]) == 1

    @pytest.mark.asyncio
    async def test_tool_list_profiles(self, temp_config):
        """Test list_profiles tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.tools.call_tool("list_profiles", {})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["total"] == 1
        assert len(data["profiles"]) == 1
        assert data["profiles"][0]["name"] == "test-profile"

    @pytest.mark.asyncio
    async def test_tool_resolve_profile(self, temp_config):
        """Test resolve_profile tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.tools.call_tool("resolve_profile", {"name": "test-profile"})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["profile"] == "test-profile"
        assert data["count"] == 1
        assert len(data["skill_ids"]) == 1

    @pytest.mark.asyncio
    async def test_tool_refresh_skills(self, temp_config):
        """Test refresh_skills tool execution."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.tools.call_tool("refresh_skills", {})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "stats" in data
        assert data["stats"]["current"] == 1

    @pytest.mark.asyncio
    async def test_prompt_activate_skill(self, temp_config):
        """Test activate_skill prompt."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        skill_id = list(server.registry._skills.keys())[0]
        result = await server.prompts.get_prompt("activate_skill", {"skill_id": skill_id})

        assert len(result.messages) == 1
        assert "TEST-SKILL" in result.messages[0].content.text
        assert "test-skill" in result.messages[0].content.text

    @pytest.mark.asyncio
    async def test_prompt_activate_profile(self, temp_config):
        """Test activate_profile prompt."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.prompts.get_prompt("activate_profile", {"profile_name": "test-profile"})

        assert len(result.messages) == 1
        assert "TEST-PROFILE" in result.messages[0].content.text
        assert "test-skill" in result.messages[0].content.text

    @pytest.mark.asyncio
    async def test_prompt_suggest_skills(self, temp_config):
        """Test suggest_skills prompt."""
        config, config_file = temp_config
        server = SkillsMCPServer(config)

        result = await server.prompts.get_prompt("suggest_skills", {"task": "test this feature"})

        assert len(result.messages) == 1
        assert "SKILL SUGGESTIONS" in result.messages[0].content.text
        assert "test-skill" in result.messages[0].content.text

    def test_license_file_and_metadata(self):
        """Test LICENSE file exists and pyproject.toml specifies MIT license."""
        license_path = Path("LICENSE")
        assert license_path.exists(), "LICENSE file is missing"
        content = license_path.read_text(encoding="utf-8")
        assert "MIT License" in content

        pyproject_path = Path("pyproject.toml")
        pyproject_content = pyproject_path.read_text(encoding="utf-8")
        assert 'license = { text = "MIT" }' in pyproject_content