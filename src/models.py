"""Core data models for the skills MCP server."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path


@dataclass
class SkillMetadata:
    """Normalized metadata for a skill."""
    id: str
    name: str
    description: str
    category: str = ""
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    license: str = ""
    argument_hint: str = ""
    preamble_tier: int = 0
    path: str = ""
    files: List[str] = field(default_factory=list)
    raw_frontmatter: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Skill:
    """A complete skill with metadata and content."""
    metadata: SkillMetadata
    content: str
    supporting_files: Dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def name(self) -> str:
        return self.metadata.name


@dataclass
class Profile:
    """A profile/bundle combining multiple skills."""
    name: str
    description: str
    skills: List[str] = field(default_factory=list)
    profiles: List[str] = field(default_factory=list)
    stages: Dict[str, List[str]] = field(default_factory=dict)
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Result from skill search."""
    skill_id: str
    name: str
    description: str
    category: str
    score: float
    matched_fields: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)