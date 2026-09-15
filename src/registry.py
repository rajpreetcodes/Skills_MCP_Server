"""Skill registry with dynamic discovery and caching."""
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from threading import Lock

from .skill_loader import SkillLoader
from .models import Skill, SkillMetadata, SearchResult


class SkillRegistry:
    """Manages skill discovery, loading, and caching."""

    def __init__(self, skill_root: Path):
        self.skill_root = Path(skill_root).resolve()
        self.loader = SkillLoader(self.skill_root)
        self._skills: Dict[str, Skill] = {}
        self._metadata_index: Dict[str, SkillMetadata] = {}
        self._category_index: Dict[str, List[str]] = {}
        self._tag_index: Dict[str, List[str]] = {}
        self._last_refresh = 0.0
        self._lock = Lock()
        self._refresh()

    def _refresh(self) -> None:
        """Reload all skills from disk atomically."""
        new_skills: Dict[str, Skill] = {}
        new_metadata_index: Dict[str, SkillMetadata] = {}
        new_category_index: Dict[str, List[str]] = {}
        new_tag_index: Dict[str, List[str]] = {}

        skill_dirs = self.loader.discover_skills()
        for skill_dir in skill_dirs:
            skill = self.loader.load_skill(skill_dir)
            if skill:
                new_skills[skill.id] = skill
                new_metadata_index[skill.id] = skill.metadata

                # Index by category
                cat = skill.metadata.category or 'uncategorized'
                if cat not in new_category_index:
                    new_category_index[cat] = []
                new_category_index[cat].append(skill.id)

                # Index by tags
                for tag in skill.metadata.tags:
                    if tag not in new_tag_index:
                        new_tag_index[tag] = []
                    new_tag_index[tag].append(skill.id)

        with self._lock:
            self._skills = new_skills
            self._metadata_index = new_metadata_index
            self._category_index = new_category_index
            self._tag_index = new_tag_index
            self._last_refresh = time.time()

    def refresh(self) -> Dict[str, int]:
        """Public refresh method with stats."""
        old_count = len(self._skills)
        self._refresh()
        new_count = len(self._skills)
        return {"previous": old_count, "current": new_count, "changed": new_count - old_count}

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID or short name."""
        if skill_id in self._skills:
            return self._skills[skill_id]
        for sid, skill in self._skills.items():
            if skill.metadata.name == skill_id or sid.endswith(f".{skill_id}"):
                return skill
        return None

    def get_skill_metadata(self, skill_id: str) -> Optional[SkillMetadata]:
        """Get skill metadata by ID or short name."""
        if skill_id in self._metadata_index:
            return self._metadata_index[skill_id]
        for sid, meta in self._metadata_index.items():
            if meta.name == skill_id or sid.endswith(f".{skill_id}"):
                return meta
        return None

    def list_skills(self, category: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[SkillMetadata]:
        """List skills with optional category filter."""
        if category:
            ids = list(self._category_index.get(category, []))
        else:
            ids = list(self._metadata_index.keys())

        ids.sort()
        paginated = ids[offset:offset + limit]
        return [self._metadata_index[sid] for sid in paginated if sid in self._metadata_index]

    def get_categories(self) -> List[str]:
        """Get all categories."""
        return sorted(self._category_index.keys())

    def get_skills_by_category(self, category: str) -> List[SkillMetadata]:
        """Get all skills in a category."""
        ids = self._category_index.get(category, [])
        return [self._metadata_index[sid] for sid in sorted(ids) if sid in self._metadata_index]

    def search_skills(self, query: str, limit: int = 20, offset: int = 0) -> List[SearchResult]:
        """Search skills by query across name, description, tags, triggers."""
        query_lower = query.lower().strip()
        if not query_lower:
            return []

        query_terms = query_lower.split()
        if not query_terms:
            return []

        metadata_snapshot = list(self._metadata_index.items())
        results = []

        for skill_id, metadata in metadata_snapshot:
            score = 0.0
            matched = []

            # Name match (highest weight)
            name_lower = metadata.name.lower()
            for term in query_terms:
                if term in name_lower:
                    score += 10.0
                    matched.append('name')

            # Description match
            desc_lower = metadata.description.lower()
            for term in query_terms:
                if term in desc_lower:
                    score += 5.0
                    matched.append('description')

            # Tag match
            for tag in metadata.tags:
                tag_lower = tag.lower()
                for term in query_terms:
                    if term in tag_lower:
                        score += 8.0
                        matched.append('tags')

            # Trigger match
            for trigger in metadata.triggers:
                trigger_lower = trigger.lower()
                for term in query_terms:
                    if term in trigger_lower:
                        score += 7.0
                        matched.append('triggers')

            # Category match
            cat_lower = metadata.category.lower()
            for term in query_terms:
                if term in cat_lower:
                    score += 3.0
                    matched.append('category')

            # ID match
            for term in query_terms:
                if term in skill_id.lower():
                    score += 2.0
                    matched.append('id')

            if score > 0:
                results.append(SearchResult(
                    skill_id=skill_id,
                    name=metadata.name,
                    description=metadata.description,
                    category=metadata.category,
                    score=score,
                    matched_fields=list(set(matched)),
                    tags=metadata.tags
                ))

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[offset:offset + limit]

    def get_all_skill_ids(self) -> List[str]:
        """Get all skill IDs."""
        return sorted(self._skills.keys())

    def get_stats(self) -> Dict[str, any]:
        """Get registry statistics."""
        return {
            "total_skills": len(self._skills),
            "categories": len(self._category_index),
            "tags": len(self._tag_index),
            "last_refresh": self._last_refresh,
            "skill_root": str(self.skill_root)
        }