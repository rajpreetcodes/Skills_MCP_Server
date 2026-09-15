"""Loads and resolves skill profiles/bundles."""
import logging
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Set
from .models import Profile
from .registry import SkillRegistry

logger = logging.getLogger(__name__)


class ProfileLoader:
    """Loads profiles from YAML files and resolves skill dependencies."""

    def __init__(self, profile_dir: Path, registry: SkillRegistry):
        self.profile_dir = Path(profile_dir).resolve()
        self.registry = registry
        self._profiles: Dict[str, Profile] = {}
        self._load_profiles()

    def _load_profiles(self) -> None:
        """Load all profile YAML files."""
        if not self.profile_dir.exists():
            return

        for profile_file in sorted(list(self.profile_dir.glob('*.yaml')) + list(self.profile_dir.glob('*.yml'))):
            try:
                content = profile_file.read_text(encoding='utf-8').strip()
                docs = [doc for doc in yaml.safe_load_all(content) if isinstance(doc, dict)]
                data = docs[0] if docs else {}
                profile = Profile(
                    name=data.get('name', profile_file.stem),
                    description=data.get('description', ''),
                    skills=data.get('skills', []),
                    profiles=data.get('profiles', []),
                    stages=data.get('stages', {}),
                    version=str(data.get('version', '1.0.0')),
                    metadata=data.get('metadata', {})
                )
                self._profiles[profile.name] = profile
            except Exception as e:
                logger.error(f"Error loading profile {profile_file}: {e}")

    def get_profile(self, name: str) -> Optional[Profile]:
        """Get a profile by name."""
        return self._profiles.get(name)

    def list_profiles(self) -> List[Profile]:
        """List all profiles."""
        return list(self._profiles.values())

    def resolve_profile(self, name: str, visited: Optional[Set[str]] = None) -> List[str]:
        """
        Resolve a profile to a flat list of skill IDs.
        Handles nested profiles and detects cycles.
        """
        if visited is None:
            visited = set()

        if name in visited:
            raise ValueError(f"Circular profile dependency detected: {' -> '.join(visited)} -> {name}")

        visited.add(name)
        profile = self._profiles.get(name)
        if not profile:
            raise ValueError(f"Profile not found: {name}")

        skill_ids = []

        # Resolve nested profiles first
        for nested_name in profile.profiles:
            skill_ids.extend(self.resolve_profile(nested_name, visited.copy()))

        # Add direct skills
        for skill_ref in profile.skills:
            resolved = self._resolve_skill_reference(skill_ref)
            if resolved:
                skill_ids.extend(resolved)

        visited.remove(name)
        # Deduplicate while preserving resolution order
        return list(dict.fromkeys(skill_ids))

    def _resolve_skill_reference(self, ref: str) -> List[str]:
        """Resolve a skill reference (exact ID, prefix, or name) to skill IDs."""
        # Exact match
        if ref in self.registry._skills:
            return [ref]

        # Prefix match
        if ref.endswith('.*'):
            prefix = ref[:-2]
            return [sid for sid in self.registry._skills if sid.startswith(prefix)]
        elif ref.endswith('.'):
            prefix = ref[:-1]
            return [sid for sid in self.registry._skills if sid.startswith(prefix)]

        # Category match
        if ref in self.registry._category_index:
            return list(self.registry._category_index[ref])

        # Name partial match
        matches = []
        ref_lower = ref.lower()
        for sid, metadata in self.registry._metadata_index.items():
            if ref_lower in metadata.name.lower() or ref_lower in sid.lower():
                matches.append(sid)
        if matches:
            return matches

        return []

    def get_profile_skills(self, name: str) -> List[str]:
        """Get resolved skill IDs for a profile (alias for resolve_profile)."""
        return self.resolve_profile(name)

    def get_stage_skills(self, profile_name: str, stage: str, visited: Optional[Set[str]] = None) -> List[str]:
        """Get skill IDs for a specific stage in a profile, including nested profiles."""
        if visited is None:
            visited = set()

        if profile_name in visited:
            return []
        visited.add(profile_name)

        profile = self._profiles.get(profile_name)
        if not profile:
            return []

        skill_ids = []

        # Recurse into nested profiles
        for nested_name in profile.profiles:
            skill_ids.extend(self.get_stage_skills(nested_name, stage, visited.copy()))

        # Add direct stage skills
        if stage in profile.stages:
            for skill_ref in profile.stages[stage]:
                resolved = self._resolve_skill_reference(skill_ref)
                skill_ids.extend(resolved)

        visited.remove(profile_name)
        return list(dict.fromkeys(skill_ids))