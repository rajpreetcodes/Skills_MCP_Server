"""Loads and parses skill definitions from the filesystem."""
import logging
import re
import sys
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, List
from .models import Skill, SkillMetadata

logger = logging.getLogger(__name__)


class SkillLoader:
    """Loads skills from the filesystem."""

    def __init__(self, skill_root: Path):
        self.skill_root = Path(skill_root).resolve()
        self._frontmatter_pattern = re.compile(r'^---\r?\n(.*?)\r?\n---', re.DOTALL)

    def discover_skills(self) -> List[Path]:
        """Find all skill directories containing SKILL.md recursively."""
        skills = set()
        if not self.skill_root.exists():
            return []

        for skill_file in self.skill_root.rglob("SKILL.md"):
            item = skill_file.parent
            try:
                rel_parts = item.relative_to(self.skill_root).parts
                if any(p.startswith('.') or p.startswith('_') for p in rel_parts):
                    continue
                skills.add(item)
            except Exception:
                continue
        return sorted(list(skills))

    def load_skill(self, skill_dir: Path) -> Optional[Skill]:
        """Load a single skill from its directory."""
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None

        try:
            content = skill_file.read_text(encoding='utf-8')
            metadata = self._parse_frontmatter(content, skill_dir)
            supporting_files = self._load_supporting_files(skill_dir)

            # Remove frontmatter from content for clean display
            clean_content = self._remove_frontmatter(content)

            return Skill(
                metadata=metadata,
                content=clean_content,
                supporting_files=supporting_files
            )
        except Exception as e:
            logger.error(f"Error loading skill {skill_dir.name}: {e}")
            return None

    def _parse_frontmatter(self, content: str, skill_dir: Path) -> SkillMetadata:
        """Parse YAML frontmatter from SKILL.md."""
        match = self._frontmatter_pattern.match(content)
        frontmatter = {}
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1)) or {}
            except yaml.YAMLError:
                pass

        skill_name = frontmatter.get('name', skill_dir.name)
        skill_id = self._generate_skill_id(skill_dir, skill_name)

        # Extract category from frontmatter first, fall back to directory inference
        raw_category = frontmatter.get('category')
        if raw_category and str(raw_category).strip():
            category = str(raw_category).strip()
        else:
            category = self._infer_category(skill_dir)

        # Collect all files in skill directory using forward slashes
        files = []
        for f in skill_dir.rglob('*'):
            if f.is_file() and not f.name.startswith('.'):
                rel = f.relative_to(skill_dir)
                files.append(rel.as_posix())

        return SkillMetadata(
            id=skill_id,
            name=skill_name,
            description=frontmatter.get('description', '').strip(),
            category=category,
            version=str(frontmatter.get('version', '1.0.0')),
            tags=frontmatter.get('tags', []) if isinstance(frontmatter.get('tags'), list) else [],
            triggers=frontmatter.get('triggers', []) if isinstance(frontmatter.get('triggers'), list) else [],
            allowed_tools=frontmatter.get('allowed-tools', []) if isinstance(frontmatter.get('allowed-tools'), list) else [],
            license=frontmatter.get('license', ''),
            argument_hint=frontmatter.get('argument-hint', ''),
            preamble_tier=frontmatter.get('preamble-tier', 0) if isinstance(frontmatter.get('preamble-tier'), int) else 0,
            path=skill_dir.relative_to(self.skill_root).as_posix(),
            files=sorted(files),
            raw_frontmatter=frontmatter
        )

    def _generate_skill_id(self, skill_dir: Path, name: str) -> str:
        """Generate a stable skill ID from path and name."""
        # Use relative path from skill_root as namespace
        rel_path = skill_dir.relative_to(self.skill_root)
        namespace = str(rel_path.as_posix()).replace('/', '.')
        # Clean up the name for ID
        clean_name = re.sub(r'[^a-zA-Z0-9-]', '-', name.lower())
        clean_name = re.sub(r'-+', '-', clean_name).strip('-')
        return f"{namespace}.{clean_name}"

    def _infer_category(self, skill_dir: Path) -> str:
        """Infer category from directory name or structure."""
        parent = skill_dir.parent.name
        if parent != 'skills' and parent != '.claude':
            return parent
        return skill_dir.name.split('-')[0] if '-' in skill_dir.name else 'general'

    def _remove_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from content."""
        return self._frontmatter_pattern.sub('', content).strip()

    def _load_supporting_files(self, skill_dir: Path) -> Dict[str, str]:
        """Load supporting reference files from skill directory."""
        supporting = {}
        for ext in ['.md', '.txt', '.json', '.yaml', '.yml']:
            for f in skill_dir.rglob(f'*{ext}'):
                if f.is_file() and f.name != 'SKILL.md':
                    try:
                        rel_posix = f.relative_to(skill_dir).as_posix()
                        if f.stat().st_size <= 512 * 1024:
                            supporting[rel_posix] = f.read_text(encoding='utf-8')
                    except Exception as e:
                        logger.warning(f"Could not load supporting file {f}: {e}")
        return supporting