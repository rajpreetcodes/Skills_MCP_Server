"""Tests for skill search functionality."""
import pytest
import tempfile
from pathlib import Path

from src.registry import SkillRegistry


class TestSkillSearch:
    """Test skill search with various queries."""

    @pytest.fixture
    def temp_skills(self):
        """Create skills with diverse content for search testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            skills_data = [
                {
                    "name": "design-system",
                    "category": "ui-ux",
                    "description": "Create consistent design systems with tokens, components, and guidelines",
                    "tags": ["design", "system", "tokens", "components"],
                    "triggers": ["design system", "create design tokens", "build component library"]
                },
                {
                    "name": "debugging-expert",
                    "category": "software",
                    "description": "Expert debugging techniques for production issues",
                    "tags": ["debugging", "troubleshooting", "production", "root-cause"],
                    "triggers": ["debug this", "fix bug", "production issue", "root cause analysis"]
                },
                {
                    "name": "security-audit",
                    "category": "security",
                    "description": "Comprehensive security auditing for web applications",
                    "tags": ["security", "audit", "penetration-testing", "owasp"],
                    "triggers": ["security audit", "penetration test", "vulnerability assessment"]
                },
                {
                    "name": "api-design",
                    "category": "software",
                    "description": "Design RESTful and GraphQL APIs with best practices",
                    "tags": ["api", "rest", "graphql", "design"],
                    "triggers": ["design api", "rest api", "graphql schema"]
                },
                {
                    "name": "research-methodology",
                    "category": "research",
                    "description": "Structured research methodologies for market and technical analysis",
                    "tags": ["research", "methodology", "analysis", "market-research"],
                    "triggers": ["research this", "market analysis", "competitive research"]
                }
            ]

            for data in skills_data:
                skill_dir = root / data["name"]
                skill_dir.mkdir()
                frontmatter = {
                    "name": data["name"],
                    "description": data["description"],
                    "category": data["category"],
                    "tags": data["tags"],
                    "triggers": data["triggers"]
                }
                import yaml
                fm_text = yaml.dump(frontmatter)
                content = f"""---
{fm_text}---
# {data['name']}

{data['description']}

Detailed content for {data['name']}.
"""
                (skill_dir / "SKILL.md").write_text(content)

            yield root

    def test_search_by_keyword(self, temp_skills):
        """Test search finds skills by keyword in description."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("design", limit=10)
        assert len(results) >= 2
        skill_names = [r.name for r in results]
        assert "design-system" in skill_names
        assert "api-design" in skill_names

    def test_search_by_tag(self, temp_skills):
        """Test search finds skills by tag."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("security", limit=10)
        assert len(results) >= 1
        assert any("security-audit" in r.skill_id for r in results)

    def test_search_by_trigger(self, temp_skills):
        """Test search finds skills by trigger phrase."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("debug this", limit=10)
        assert len(results) >= 1
        assert any("debugging-expert" in r.skill_id for r in results)

    def test_search_by_category(self, temp_skills):
        """Test search finds skills by category name."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("ui-ux", limit=10)
        assert len(results) >= 1
        assert any("design-system" in r.skill_id for r in results)

    def test_search_ranking(self, temp_skills):
        """Test results are ranked by relevance."""
        registry = SkillRegistry(temp_skills)
        # "design system" should match design-system skill highest (name + trigger + tag)
        results = registry.search_skills("design system", limit=10)
        assert len(results) >= 1
        # First result should be design-system
        assert "design-system" in results[0].skill_id
        assert results[0].score > results[-1].score if len(results) > 1 else True

    def test_search_case_insensitive(self, temp_skills):
        """Test search is case insensitive."""
        registry = SkillRegistry(temp_skills)
        results_lower = registry.search_skills("debug", limit=10)
        results_upper = registry.search_skills("DEBUG", limit=10)
        results_mixed = registry.search_skills("DeBuG", limit=10)

        assert len(results_lower) == len(results_upper) == len(results_mixed)
        assert all("debugging-expert" in r.skill_id for r in results_lower)

    def test_search_empty_query(self, temp_skills):
        """Test search with empty query returns empty results."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("", limit=10)
        assert len(results) == 0

    def test_search_limit(self, temp_skills):
        """Test search respects limit parameter."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("design", limit=1)
        assert len(results) <= 1

    def test_search_matched_fields(self, temp_skills):
        """Test matched_fields are populated correctly."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("design system tokens", limit=10)
        assert len(results) >= 1
        # Should match multiple fields
        top = results[0]
        assert len(top.matched_fields) > 0
        assert any(f in top.matched_fields for f in ['name', 'description', 'tags', 'triggers'])

    def test_search_partial_matches(self, temp_skills):
        """Test partial word matching."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("penetration", limit=10)
        assert len(results) >= 1
        assert any("security-audit" in r.skill_id for r in results)

    def test_search_no_results(self, temp_skills):
        """Test search with no matches."""
        registry = SkillRegistry(temp_skills)
        results = registry.search_skills("xyzunicornmagic", limit=10)
        assert len(results) == 0