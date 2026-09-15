"""MCP Tools for the skills server."""
import json
from typing import List, Optional, Dict, Any, Union
from mcp.types import Tool, TextContent, CallToolResult
from .registry import SkillRegistry
from .profile_loader import ProfileLoader
from .models import SkillMetadata, SearchResult


class SkillsTools:
    """MCP tool implementations."""

    def __init__(self, registry: SkillRegistry, profile_loader: ProfileLoader):
        self.registry = registry
        self.profile_loader = profile_loader

    def get_tools(self) -> List[Tool]:
        """Return all available MCP tools."""
        return [
            Tool(
                name="list_skills",
                description="List available skills with lightweight metadata. Use for browsing the skill catalog. Supports pagination and category filtering.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Filter by category (e.g., 'ui-ux', 'research', 'software')"},
                        "limit": {"type": "integer", "default": 50, "maximum": 200, "description": "Maximum results to return"},
                        "offset": {"type": "integer", "default": 0, "description": "Pagination offset"}
                    }
                }
            ),
            Tool(
                name="search_skills",
                description="Search skills by natural language query. Returns ranked results with relevance scores. Use when you need skills for a specific task.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query (e.g., 'design a dashboard', 'debug python', 'security audit')"},
                        "limit": {"type": "integer", "default": 10, "maximum": 50, "description": "Maximum results to return"},
                        "offset": {"type": "integer", "default": 0, "description": "Pagination offset"}
                    },
                    "required": ["query"]
                }
            ),
            Tool(
                name="get_skill",
                description="Get complete skill instructions and metadata by skill ID. Use after identifying relevant skills via search_skills or list_skills.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "description": "Exact skill ID (e.g., 'ui-ux-pro-max.ui-ux-pro-max', 'ponytail.ponytail')"},
                        "include_supporting": {"type": "boolean", "default": False, "description": "Include supporting reference files"}
                    },
                    "required": ["skill_id"]
                }
            ),
            Tool(
                name="get_skills",
                description="Get multiple skills at once by their IDs. Efficient batch retrieval for multi-skill tasks.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "skill_ids": {"type": "array", "items": {"type": "string"}, "description": "Array of skill IDs to retrieve"},
                        "include_supporting": {"type": "boolean", "default": False, "description": "Include supporting reference files"}
                    },
                    "required": ["skill_ids"]
                }
            ),
            Tool(
                name="list_profiles",
                description="List all available skill profiles/bundles. Profiles combine multiple skills for common workflows.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="get_profile",
                description="Get a profile definition and its resolved skill IDs. Use to understand what skills a profile includes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Profile name (e.g., 'product-builder', 'senior-engineer')"}
                    },
                    "required": ["name"]
                }
            ),
            Tool(
                name="resolve_profile",
                description="Resolve a profile to its constituent skill IDs (including nested profiles). Returns flat list of skill IDs ready for get_skills.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Profile name"},
                        "stage": {"type": "string", "description": "Optional: resolve only a specific stage (e.g., 'research', 'design', 'implementation')"}
                    },
                    "required": ["name"]
                }
            ),
            Tool(
                name="refresh_skills",
                description="Reload the skill registry from disk. Use after adding/removing skills in the skill directory.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="get_categories",
                description="List all skill categories for browsing.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="get_skill_stats",
                description="Get registry statistics (total skills, categories, etc.).",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            )
        ]

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Union[List[TextContent], CallToolResult]:
        """Execute a tool by name."""
        try:
            if name == "list_skills":
                return await self._list_skills(arguments)
            elif name == "search_skills":
                return await self._search_skills(arguments)
            elif name == "get_skill":
                return await self._get_skill(arguments)
            elif name == "get_skills":
                return await self._get_skills(arguments)
            elif name == "list_profiles":
                return await self._list_profiles(arguments)
            elif name == "get_profile":
                return await self._get_profile(arguments)
            elif name == "resolve_profile":
                return await self._resolve_profile(arguments)
            elif name == "refresh_skills":
                return await self._refresh_skills(arguments)
            elif name == "get_categories":
                return await self._get_categories(arguments)
            elif name == "get_skill_stats":
                return await self._get_skill_stats(arguments)
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                    is_error=True
                )
        except Exception as e:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error: {str(e)}")],
                is_error=True
            )

    async def _list_skills(self, args: Dict) -> List[TextContent]:
        category = args.get("category")
        limit = args.get("limit", 50)
        offset = args.get("offset", 0)

        skills = self.registry.list_skills(category, limit, offset)
        if category:
            total_count = len(self.registry._category_index[category]) if category in self.registry._category_index else 0
        else:
            total_count = len(self.registry._metadata_index)

        result = {
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description[:200] + "..." if len(s.description) > 200 else s.description,
                    "category": s.category,
                    "version": s.version,
                    "tags": s.tags[:10],
                    "triggers": s.triggers[:5]
                }
                for s in skills
            ],
            "total": total_count,
            "category": category,
            "limit": limit,
            "offset": offset
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _search_skills(self, args: Dict) -> Union[List[TextContent], CallToolResult]:
        query = args.get("query", "")
        limit = args.get("limit", 10)
        offset = args.get("offset", 0)

        if not query:
            return CallToolResult(
                content=[TextContent(type="text", text="Error: query parameter required")],
                is_error=True
            )

        results = self.registry.search_skills(query, limit, offset)
        result = {
            "query": query,
            "results": [
                {
                    "skill_id": r.skill_id,
                    "name": r.name,
                    "description": r.description[:200] + "..." if len(r.description) > 200 else r.description,
                    "category": r.category,
                    "score": round(r.score, 2),
                    "matched_fields": r.matched_fields,
                    "tags": r.tags[:10]
                }
                for r in results
            ],
            "total_matches": len(results),
            "limit": limit,
            "offset": offset
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _get_skill(self, args: Dict) -> Union[List[TextContent], CallToolResult]:
        skill_id = args.get("skill_id", "")
        include_supporting = args.get("include_supporting", False)

        if not skill_id:
            return CallToolResult(
                content=[TextContent(type="text", text="Error: skill_id parameter required")],
                is_error=True
            )

        skill = self.registry.get_skill(skill_id)
        if not skill:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Skill not found: {skill_id}")],
                is_error=True
            )

        result = {
            "metadata": {
                "id": skill.metadata.id,
                "name": skill.metadata.name,
                "description": skill.metadata.description,
                "category": skill.metadata.category,
                "version": skill.metadata.version,
                "tags": skill.metadata.tags,
                "triggers": skill.metadata.triggers,
                "allowed_tools": skill.metadata.allowed_tools,
                "license": skill.metadata.license,
                "argument_hint": skill.metadata.argument_hint,
                "preamble_tier": skill.metadata.preamble_tier,
                "path": skill.metadata.path,
                "files": skill.metadata.files
            },
            "content": skill.content
        }

        if include_supporting:
            result["supporting_files"] = skill.supporting_files

        return [TextContent(type="text", text=self._format_json(result))]

    async def _get_skills(self, args: Dict) -> Union[List[TextContent], CallToolResult]:
        skill_ids = args.get("skill_ids", [])
        include_supporting = args.get("include_supporting", False)

        if not skill_ids:
            return CallToolResult(
                content=[TextContent(type="text", text="Error: skill_ids array required")],
                is_error=True
            )

        skills = []
        not_found = []
        for sid in skill_ids:
            skill = self.registry.get_skill(sid)
            if skill:
                skill_data = {
                    "metadata": {
                        "id": skill.metadata.id,
                        "name": skill.metadata.name,
                        "description": skill.metadata.description,
                        "category": skill.metadata.category,
                        "version": skill.metadata.version,
                        "tags": skill.metadata.tags,
                        "triggers": skill.metadata.triggers,
                        "allowed_tools": skill.metadata.allowed_tools,
                        "license": skill.metadata.license,
                        "argument_hint": skill.metadata.argument_hint,
                        "preamble_tier": skill.metadata.preamble_tier,
                        "path": skill.metadata.path,
                        "files": skill.metadata.files
                    },
                    "content": skill.content
                }
                if include_supporting:
                    skill_data["supporting_files"] = skill.supporting_files
                skills.append(skill_data)
            else:
                not_found.append(sid)

        result = {
            "skills": skills,
            "requested": len(skill_ids),
            "found": len(skills),
            "not_found": not_found
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _list_profiles(self, args: Dict) -> List[TextContent]:
        profiles = self.profile_loader.list_profiles()
        result = {
            "profiles": [
                {
                    "name": p.name,
                    "description": p.description,
                    "skill_count": len(p.skills),
                    "profile_count": len(p.profiles),
                    "stages": list(p.stages.keys()),
                    "version": p.version
                }
                for p in profiles
            ],
            "total": len(profiles)
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _get_profile(self, args: Dict) -> Union[List[TextContent], CallToolResult]:
        name = args.get("name", "")

        if not name:
            return CallToolResult(
                content=[TextContent(type="text", text="Error: name parameter required")],
                is_error=True
            )

        profile = self.profile_loader.get_profile(name)
        if not profile:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Profile not found: {name}")],
                is_error=True
            )

        try:
            resolved = self.profile_loader.resolve_profile(name)
        except Exception as e:
            resolved = [f"Error resolving: {e}"]

        result = {
            "name": profile.name,
            "description": profile.description,
            "skills": profile.skills,
            "profiles": profile.profiles,
            "stages": profile.stages,
            "version": profile.version,
            "metadata": profile.metadata,
            "resolved_skill_ids": resolved
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _resolve_profile(self, args: Dict) -> Union[List[TextContent], CallToolResult]:
        name = args.get("name", "")
        stage = args.get("stage")

        if not name:
            return CallToolResult(
                content=[TextContent(type="text", text="Error: name parameter required")],
                is_error=True
            )

        try:
            if stage:
                skill_ids = self.profile_loader.get_stage_skills(name, stage)
            else:
                skill_ids = self.profile_loader.resolve_profile(name)

            result = {
                "profile": name,
                "stage": stage,
                "skill_ids": skill_ids,
                "count": len(skill_ids)
            }
            return [TextContent(type="text", text=self._format_json(result))]
        except Exception as e:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error resolving profile: {e}")],
                is_error=True
            )

    async def _refresh_skills(self, args: Dict) -> List[TextContent]:
        stats = self.registry.refresh()
        result = {
            "message": "Skill registry refreshed",
            "stats": stats
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _get_categories(self, args: Dict) -> List[TextContent]:
        categories = self.registry.get_categories()
        result = {
            "categories": categories,
            "total": len(categories)
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _get_skill_stats(self, args: Dict) -> List[TextContent]:
        stats = self.registry.get_stats()
        return [TextContent(type="text", text=self._format_json(stats))]

    def _format_json(self, data: Any) -> str:
        return json.dumps(data, indent=2, ensure_ascii=False)