"""MCP Resources for the skills server."""
from typing import List, Optional
from mcp.types import Resource, ResourceContents, TextResourceContents
from .registry import SkillRegistry


class SkillsResources:
    """MCP resource implementations."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def get_resources(self) -> List[Resource]:
        """Return all available MCP resources."""
        resources = []

        # Skill list resource
        resources.append(Resource(
            uri="skill://list",
            name="Skill Catalog",
            description="Complete list of all available skills with metadata",
            mimeType="application/json"
        ))

        # Categories resource
        resources.append(Resource(
            uri="skill://categories",
            name="Skill Categories",
            description="All skill categories",
            mimeType="application/json"
        ))

        # Individual skill resources
        for skill_id, metadata in self.registry._metadata_index.items():
            resources.append(Resource(
                uri=f"skill://{skill_id}",
                name=f"Skill: {metadata.name}",
                description=metadata.description[:200],
                mimeType="text/markdown"
            ))

            # Supporting files as separate resources
            for rel_path in metadata.files:
                if rel_path != "SKILL.md" and rel_path.endswith(('.md', '.txt', '.json', '.yaml', '.yml')):
                    resources.append(Resource(
                        uri=f"skill://{skill_id}/{rel_path}",
                        name=f"{metadata.name} / {rel_path}",
                        description=f"Supporting file: {rel_path}",
                        mimeType="text/plain"
                    ))

        return resources

    async def read_resource(self, uri: str) -> List[ResourceContents]:
        """Read a resource by URI."""
        if uri == "skill://list":
            return await self._read_skill_list()
        elif uri == "skill://categories":
            return await self._read_categories()
        elif uri.startswith("skill://"):
            return await self._read_skill_resource(uri)
        else:
            return [TextResourceContents(
                uri=uri,
                mimeType="text/plain",
                text=f"Unknown resource: {uri}"
            )]

    async def _read_skill_list(self) -> List[ResourceContents]:
        import json
        skills = []
        for metadata in self.registry._metadata_index.values():
            skills.append({
                "id": metadata.id,
                "name": metadata.name,
                "description": metadata.description,
                "category": metadata.category,
                "version": metadata.version,
                "tags": metadata.tags,
                "triggers": metadata.triggers
            })
        return [TextResourceContents(
            uri="skill://list",
            mimeType="application/json",
            text=json.dumps({"skills": skills, "total": len(skills)}, indent=2)
        )]

    async def _read_categories(self) -> List[ResourceContents]:
        import json
        categories = {}
        for cat, skill_ids in self.registry._category_index.items():
            categories[cat] = len(skill_ids)
        return [TextResourceContents(
            uri="skill://categories",
            mimeType="application/json",
            text=json.dumps({"categories": categories, "total": len(categories)}, indent=2)
        )]

    async def _read_skill_resource(self, uri: str) -> List[ResourceContents]:
        # Parse URI: skill://<skill-id>[/<file-path>]
        path_part = uri[8:]  # Remove "skill://"
        parts = path_part.split('/', 1)
        skill_id = parts[0]

        skill = self.registry.get_skill(skill_id)
        if not skill:
            return [TextResourceContents(
                uri=uri,
                mimeType="text/plain",
                text=f"Skill not found: {skill_id}"
            )]

        if len(parts) == 1:
            # Main skill content
            content = f"# {skill.metadata.name}\n\n"
            content += f"**ID:** {skill.metadata.id}\n"
            content += f"**Category:** {skill.metadata.category}\n"
            content += f"**Version:** {skill.metadata.version}\n"
            if skill.metadata.tags:
                content += f"**Tags:** {', '.join(skill.metadata.tags)}\n"
            if skill.metadata.triggers:
                content += f"**Triggers:** {', '.join(skill.metadata.triggers)}\n"
            content += f"\n---\n\n{skill.content}"
            return [TextResourceContents(
                uri=uri,
                mimeType="text/markdown",
                text=content
            )]
        else:
            # Supporting file
            file_path = parts[1].replace('\\', '/')
            if file_path in skill.supporting_files:
                return [TextResourceContents(
                    uri=uri,
                    mimeType="text/plain",
                    text=skill.supporting_files[file_path]
                )]

            # Lazy load from disk on demand with strict path traversal validation
            try:
                skill_dir = (self.registry.skill_root / skill.metadata.path).resolve()
                target_file = (skill_dir / file_path).resolve()
                if target_file.is_relative_to(skill_dir) and target_file.is_file():
                    content = target_file.read_text(encoding='utf-8')
                    return [TextResourceContents(
                        uri=uri,
                        mimeType="text/plain",
                        text=content
                    )]
            except Exception:
                pass

            return [TextResourceContents(
                uri=uri,
                mimeType="text/plain",
                text=f"File not found: {file_path}"
            )]