"""Integration tests for Skills MCP Server HTTP transport and concurrency."""
import pytest
import tempfile
import threading
from pathlib import Path
from starlette.testclient import TestClient

from src.http_server import SkillsHTTPServer
from src.registry import SkillRegistry
from src.skill_loader import SkillLoader
from src.profile_loader import ProfileLoader


class TestIntegration:
    """Integration test suite covering HTTP, Auth, CRLF, and concurrency."""

    @pytest.fixture
    def test_env(self):
        """Set up a clean temporary environment with skills and profiles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_root = root / "skills"
            profile_dir = root / "profiles"
            skill_root.mkdir()
            profile_dir.mkdir()

            # Create skill with CRLF endings to test Windows compatibility
            skill_a = skill_root / "skill-a"
            skill_a.mkdir()
            (skill_a / "SKILL.md").write_bytes(
                b"---\r\nname: skill-a\r\ndescription: Skill A\r\ncategory: core\r\ntags: [a]\r\n---\r\n# Skill A\r\nInstructions."
            )

            # Create second skill
            skill_b = skill_root / "skill-b"
            skill_b.mkdir()
            (skill_b / "SKILL.md").write_bytes(
                b"---\nname: skill-b\ndescription: Skill B\ncategory: core\ntags: [b]\n---\n# Skill B\nInstructions."
            )

            # Create nested profiles with stages
            (profile_dir / "base.yaml").write_text("""name: base
stages:
  dev:
    - skill-a
""")
            (profile_dir / "extended.yaml").write_text("""name: extended
profiles:
  - base
stages:
  dev:
    - skill-b
""")

            config = {
                "skill_root": str(skill_root),
                "profile_dir": str(profile_dir),
                "transport": "http",
                "host": "127.0.0.1",
                "port": 8000,
                "auth_token": "secret123"
            }
            yield config, skill_root, profile_dir

    def test_crlf_parsing(self, test_env):
        """Assert skills with Windows CRLF newlines parse correctly."""
        config, skill_root, _ = test_env
        registry = SkillRegistry(skill_root)
        skill = list(registry._skills.values())[0]
        assert skill.metadata.category == "core"
        assert skill.metadata.name == "skill-a"

    def test_nested_profile_stages(self, test_env):
        """Assert get_stage_skills resolves stages from nested profiles."""
        config, skill_root, profile_dir = test_env
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)
        skills = loader.get_stage_skills("extended", "dev")
        assert len(skills) == 2
        assert any("skill-a" in s for s in skills)
        assert any("skill-b" in s for s in skills)

    def test_http_health_unauthenticated(self, test_env):
        """Health endpoint should be accessible without auth."""
        config, _, _ = test_env
        server = SkillsHTTPServer(config)
        client = TestClient(server.app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_http_auth_bearer(self, test_env):
        """Stats endpoint requires valid auth."""
        config, _, _ = test_env
        server = SkillsHTTPServer(config)
        client = TestClient(server.app)

        # Missing token
        res_no_auth = client.get("/stats")
        assert res_no_auth.status_code == 401

        # Invalid token
        res_bad_auth = client.get("/stats", headers={"Authorization": "Bearer wrongtoken"})
        assert res_bad_auth.status_code == 403

        # Valid Bearer token
        res_ok = client.get("/stats", headers={"Authorization": "Bearer secret123"})
        assert res_ok.status_code == 200
        assert res_ok.json()["skills"] == 2

    def test_http_auth_query_token(self, test_env):
        """Verify token in query parameters works for browser EventSource."""
        config, _, _ = test_env
        server = SkillsHTTPServer(config)
        client = TestClient(server.app)

        response = client.get("/stats?token=secret123")
        assert response.status_code == 200
        assert response.json()["skills"] == 2

    def test_concurrent_refresh_and_search(self, test_env):
        """Assert concurrent refreshes do not raise dictionary mutation errors."""
        config, skill_root, _ = test_env
        registry = SkillRegistry(skill_root)

        errors = []

        def reader():
            for _ in range(50):
                try:
                    registry.search_skills("skill", limit=10)
                except Exception as exc:
                    errors.append(exc)

        def writer():
            for _ in range(10):
                try:
                    registry.refresh()
                except Exception as exc:
                    errors.append(exc)

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=writer)
        t3 = threading.Thread(target=reader)

        t1.start()
        t2.start()
        t3.start()

        t1.join()
        t2.join()
        t3.join()

        assert len(errors) == 0
