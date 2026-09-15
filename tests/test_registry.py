"""Tests for the skill registry."""
import pytest
import tempfile
import shutil
from pathlib import Path

from src.registry import SkillRegistry
from src.skill_loader import SkillLoader
from src.models import SkillMetadata


class TestSkillRegistry:
    """Test skill discovery and registry operations."""

    @pytest.fixture
    def temp_skill_dir(self):
        """Create a temporary skill directory structure for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create skill 1
            skill1 = root / "test-skill-one"
            skill1.mkdir()
            (skill1 / "SKILL.md").write_text("""---
name: test-skill-one
description: A test skill for unit testing
category: testing
tags: [test, unit]
triggers: ["test this", "run tests"]
---
# Test Skill One

This is a test skill content.
""")

            # Create skill 2
            skill2 = root / "test-skill-two"
            skill2.mkdir()
            (skill2 / "SKILL.md").write_text("""---
name: test-skill-two
description: Another test skill for testing search
category: testing
tags: [test, integration]
---
# Test Skill Two

Another test skill content.
""")

            # Create skill 3 in different category
            skill3 = root / "ui-design-skill"
            skill3.mkdir()
            (skill3 / "SKILL.md").write_text("""---
name: ui-design-skill
description: A UI design skill for testing categories
category: ui-ux
tags: [design, ui]
---
# UI Design Skill

UI design content.
""")

            yield root

    def test_discover_skills(self, temp_skill_dir):
        """Test skill discovery finds all skills."""
        loader = SkillLoader(temp_skill_dir)
        skills = loader.discover_skills()
        assert len(skills) == 3
        names = [s.name for s in skills]
        assert "test-skill-one" in names
        assert "test-skill-two" in names
        assert "ui-design-skill" in names

    def test_load_skill(self, temp_skill_dir):
        """Test loading a single skill."""
        loader = SkillLoader(temp_skill_dir)
        skills = loader.discover_skills()
        skill = loader.load_skill(skills[0])
        assert skill is not None
        assert skill.metadata.name == "test-skill-one"
        assert skill.metadata.category == "testing"
        assert "test" in skill.metadata.tags
        assert "test this" in skill.metadata.triggers
        assert "This is a test skill content" in skill.content

    def test_registry_loading(self, temp_skill_dir):
        """Test registry loads all skills."""
        registry = SkillRegistry(temp_skill_dir)
        assert len(registry._skills) == 3
        assert len(registry._metadata_index) == 3

    def test_list_skills(self, temp_skill_dir):
        """Test listing skills with pagination."""
        registry = SkillRegistry(temp_skill_dir)
        skills = registry.list_skills(limit=2)
        assert len(skills) == 2
        skills_all = registry.list_skills(limit=10)
        assert len(skills_all) == 3

    def test_list_skills_by_category(self, temp_skill_dir):
        """Test filtering skills by category."""
        registry = SkillRegistry(temp_skill_dir)
        testing_skills = registry.list_skills(category="testing")
        assert len(testing_skills) == 2
        ui_skills = registry.list_skills(category="ui-ux")
        assert len(ui_skills) == 1

    def test_get_categories(self, temp_skill_dir):
        """Test getting all categories."""
        registry = SkillRegistry(temp_skill_dir)
        categories = registry.get_categories()
        assert "testing" in categories
        assert "ui-ux" in categories

    def test_search_skills(self, temp_skill_dir):
        """Test skill search functionality."""
        registry = SkillRegistry(temp_skill_dir)
        results = registry.search_skills("test", limit=10)
        assert len(results) >= 2
        # Should match both test skills
        skill_ids = [r.skill_id for r in results]
        assert any("test-skill-one" in sid for sid in skill_ids)
        assert any("test-skill-two" in sid for sid in skill_ids)

    def test_search_by_category(self, temp_skill_dir):
        """Test search matches category."""
        registry = SkillRegistry(temp_skill_dir)
        results = registry.search_skills("ui design", limit=10)
        assert len(results) >= 1
        assert any("ui-design-skill" in r.skill_id for r in results)

    def test_get_skill(self, temp_skill_dir):
        """Test getting a specific skill by ID."""
        registry = SkillRegistry(temp_skill_dir)
        skill_ids = list(registry._skills.keys())
        skill = registry.get_skill(skill_ids[0])
        assert skill is not None
        assert isinstance(skill.metadata, SkillMetadata)

    def test_get_nonexistent_skill(self, temp_skill_dir):
        """Test getting non-existent skill returns None."""
        registry = SkillRegistry(temp_skill_dir)
        skill = registry.get_skill("nonexistent-skill")
        assert skill is None

    def test_refresh(self, temp_skill_dir):
        """Test registry refresh."""
        registry = SkillRegistry(temp_skill_dir)
        initial_count = len(registry._skills)

        # Add a new skill
        new_skill = temp_skill_dir / "new-skill"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text("""---
name: new-skill
description: Newly added skill
---
# New Skill
Content here.
""")

        stats = registry.refresh()
        assert stats["current"] == initial_count + 1
        assert stats["changed"] == 1

    def test_skill_id_generation(self, temp_skill_dir):
        """Test skill IDs are generated consistently."""
        registry = SkillRegistry(temp_skill_dir)
        skill_ids = list(registry._skills.keys())
        # IDs should be deterministic and contain namespace
        for sid in skill_ids:
            assert "." in sid  # namespace.skill-name format
            assert "test-skill" in sid or "ui-design" in sid

    def test_stats(self, temp_skill_dir):
        """Test registry statistics."""
        registry = SkillRegistry(temp_skill_dir)
        stats = registry.get_stats()
        assert stats["total_skills"] == 3
        assert stats["categories"] == 2
        assert "tags" in stats