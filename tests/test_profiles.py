"""Tests for the profile loader."""
import pytest
import tempfile
from pathlib import Path

from src.registry import SkillRegistry
from src.profile_loader import ProfileLoader


class TestProfileLoader:
    """Test profile loading and resolution."""

    @pytest.fixture
    def temp_setup(self):
        """Create temporary skill and profile directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_root = root / "skills"
            profile_dir = root / "profiles"
            skill_root.mkdir()
            profile_dir.mkdir()

            # Create test skills
            for i, (name, cat, desc) in enumerate([
                ("skill-a", "testing", "Skill A"),
                ("skill-b", "testing", "Skill B"),
                ("skill-c", "ui-ux", "Skill C"),
                ("skill-d", "research", "Skill D"),
            ]):
                skill_dir = skill_root / name
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"""---
name: {name}
description: {desc}
category: {cat}
tags: [tag{i}]
---
# {name}
Content for {name}.
""")

            # Create profiles
            (profile_dir / "simple.yaml").write_text("""name: simple
description: Simple profile with direct skills
skills:
  - skill-a
  - skill-b
""")

            (profile_dir / "nested.yaml").write_text("""name: nested
description: Profile with nested profile
profiles:
  - simple
skills:
  - skill-c
""")

            (profile_dir / "staged.yaml").write_text("""name: staged
description: Profile with stages
skills:
  - skill-a
stages:
  research:
    - skill-d
  testing:
    - skill-b
""")

            yield skill_root, profile_dir

    def test_load_profiles(self, temp_setup):
        """Test loading profiles from YAML."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        profiles = loader.list_profiles()
        assert len(profiles) == 3
        names = [p.name for p in profiles]
        assert "simple" in names
        assert "nested" in names
        assert "staged" in names

    def test_get_profile(self, temp_setup):
        """Test getting a specific profile."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        profile = loader.get_profile("simple")
        assert profile is not None
        assert profile.name == "simple"
        assert len(profile.skills) == 2

    def test_resolve_simple_profile(self, temp_setup):
        """Test resolving a simple profile to skill IDs."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        skill_ids = loader.resolve_profile("simple")
        assert len(skill_ids) == 2
        # Should contain skill-a and skill-b (with namespace prefix)
        assert any("skill-a" in sid for sid in skill_ids)
        assert any("skill-b" in sid for sid in skill_ids)

    def test_resolve_nested_profile(self, temp_setup):
        """Test resolving a profile with nested profiles."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        skill_ids = loader.resolve_profile("nested")
        # Should have skill-a, skill-b from simple + skill-c
        assert len(skill_ids) == 3
        assert any("skill-a" in sid for sid in skill_ids)
        assert any("skill-b" in sid for sid in skill_ids)
        assert any("skill-c" in sid for sid in skill_ids)

    def test_resolve_profile_with_stage(self, temp_setup):
        """Test resolving a specific stage."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        # Test research stage
        research_skills = loader.get_stage_skills("staged", "research")
        assert len(research_skills) == 1
        assert any("skill-d" in sid for sid in research_skills)

        # Test testing stage
        testing_skills = loader.get_stage_skills("staged", "testing")
        assert len(testing_skills) == 1
        assert any("skill-b" in sid for sid in testing_skills)

    def test_circular_dependency_detection(self, temp_setup):
        """Test circular profile dependency detection."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        # Create circular profile
        (profile_dir / "circular.yaml").write_text("""name: circular
description: Circular dependency
profiles:
  - circular
""")
        # Reload profiles
        loader._load_profiles()

        with pytest.raises(ValueError, match="Circular profile dependency"):
            loader.resolve_profile("circular")

    def test_nonexistent_profile(self, temp_setup):
        """Test handling of nonexistent profile."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        profile = loader.get_profile("nonexistent")
        assert profile is None

        with pytest.raises(ValueError, match="Profile not found"):
            loader.resolve_profile("nonexistent")

    def test_skill_reference_resolution(self, temp_setup):
        """Test various skill reference formats."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        # Test category reference
        (profile_dir / "by_category.yaml").write_text("""name: by_category
skills:
  - testing
""")
        loader._load_profiles()
        skill_ids = loader.resolve_profile("by_category")
        assert len(skill_ids) == 2  # skill-a and skill-b

    def test_list_profiles(self, temp_setup):
        """Test listing all profiles."""
        skill_root, profile_dir = temp_setup
        registry = SkillRegistry(skill_root)
        loader = ProfileLoader(profile_dir, registry)

        profiles = loader.list_profiles()
        assert len(profiles) == 3
        for p in profiles:
            assert hasattr(p, 'name')
            assert hasattr(p, 'description')
            assert hasattr(p, 'skills')