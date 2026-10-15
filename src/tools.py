"""MCP Tools for the skills server."""
import logging
import json
import math
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from mcp.types import Tool, TextContent, CallToolResult, ToolAnnotations
from .registry import SkillRegistry
from .profile_loader import ProfileLoader
from .models import SkillMetadata, SearchResult

logger = logging.getLogger(__name__)
_CONTEXT_TTL_SECONDS = 1800
_MAX_SEARCH_CONTEXTS = 1024
_DEFAULT_AMBIGUITY_THRESHOLD = 2.0
_QUERY_SECRET_PATTERNS = (
    (re.compile(r"(?i)\bBearer\s+\S+"), "Bearer [REDACTED]"),
    (
        re.compile(r"(?i)\b([a-z0-9_-]*(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)[a-z0-9_-]*)\s*([:=]\s*|\s+)\S+"),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)\btoken=([^&\s]+)"), "token=[REDACTED]"),
)


class SkillsTools:
    """MCP tool implementations."""

    def __init__(self, registry: SkillRegistry, profile_loader: ProfileLoader, config: Optional[Dict[str, Any]] = None):
        self.registry = registry
        self.profile_loader = profile_loader
        config = config or {}
        threshold = self._numeric_score(
            config.get("search_ambiguity_threshold", _DEFAULT_AMBIGUITY_THRESHOLD)
        )
        self.ambiguity_threshold = (
            threshold if threshold is not None and threshold >= 0
            else _DEFAULT_AMBIGUITY_THRESHOLD
        )
        log_path = config.get("correction_log_path")
        if not isinstance(log_path, (str, os.PathLike)) or not str(log_path).strip():
            log_path = "data/skill-selection-corrections.jsonl"
        self.correction_log_path = Path(log_path)
        self._search_contexts: Dict[str, Dict[str, Any]] = {}
        self._search_context_lock = threading.Lock()
        self._correction_log_lock = threading.Lock()

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
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
            ),
            Tool(
                name="search_skills",
                description="Search skills by natural language query. Returns ranked results, relevance scores, and a near-tie ambiguity indicator; pass search_context_id to get_skill to record an alternate selection.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language search query (e.g., 'design a dashboard', 'debug python', 'security audit')"},
                        "limit": {"type": "integer", "default": 10, "maximum": 50, "description": "Maximum results to return"},
                        "offset": {"type": "integer", "default": 0, "description": "Pagination offset"}
                    },
                    "required": ["query"]
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False
                )
            ),
            Tool(
                name="get_skill",
                description="Get complete skill instructions and metadata by skill ID. Use after identifying relevant skills via search_skills or list_skills.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "description": "Exact skill ID (e.g., 'ui-ux-pro-max.ui-ux-pro-max', 'ponytail.ponytail')"},
                        "include_supporting": {"type": "boolean", "default": False, "description": "Include supporting reference files"},
                        "search_context_id": {"type": "string", "description": "Optional ID returned by search_skills, used to record a non-top-ranked selection"}
                    },
                    "required": ["skill_id"]
                },
                annotations=ToolAnnotations(
                    readOnlyHint=False,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=False
                )
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
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
            ),
            Tool(
                name="list_profiles",
                description="List all available skill profiles/bundles. Profiles combine multiple skills for common workflows.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
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
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
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
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
            ),
            Tool(
                name="refresh_skills",
                description="Reload the skill registry from disk. Use after adding/removing skills in the skill directory.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
            ),
            Tool(
                name="get_categories",
                description="List all skill categories for browsing.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
            ),
            Tool(
                name="get_skill_stats",
                description="Get registry statistics (total skills, categories, etc.).",
                inputSchema={
                    "type": "object",
                    "properties": {}
                },
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False
                )
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
        context_results = (
            self.registry.search_skills(query, max(limit + offset, 2), 0)
            if results else []
        )
        top_candidates = [
            {
                "skill_id": candidate.skill_id,
                "name": candidate.name,
                "score": self._valid_score(candidate.score),
            }
            for candidate in context_results[:2]
        ]
        score_margin = None
        ambiguous = False
        if len(top_candidates) == 2:
            first_score = self._numeric_score(getattr(context_results[0], "score", None))
            second_score = self._numeric_score(getattr(context_results[1], "score", None))
            if first_score is not None and second_score is not None:
                raw_margin = abs(first_score - second_score)
                score_margin = round(raw_margin, 2)
                ambiguous = raw_margin <= self.ambiguity_threshold or math.isclose(
                    raw_margin,
                    self.ambiguity_threshold,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )

        search_context_id = (
            self._remember_search_context(query, context_results, ambiguous, score_margin, top_candidates)
            if context_results else None
        )
        result = {
            "query": query,
            "results": [
                {
                    "skill_id": r.skill_id,
                    "name": r.name,
                    "description": r.description[:200] + "..." if len(r.description) > 200 else r.description,
                    "category": r.category,
                    "score": self._valid_score(r.score),
                    "matched_fields": r.matched_fields,
                    "tags": r.tags[:10]
                }
                for r in results
            ],
            "total_matches": len(results),
            "limit": limit,
            "offset": offset,
            "ambiguous": ambiguous,
            "score_margin": score_margin,
            "top_candidates": top_candidates,
            "search_context_id": search_context_id
        }
        return [TextContent(type="text", text=self._format_json(result))]

    async def _get_skill(self, args: Dict) -> Union[List[TextContent], CallToolResult]:
        skill_id = args.get("skill_id", "")
        include_supporting = args.get("include_supporting", False)
        search_context_id = args.get("search_context_id")

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

        selection_diagnostics = self._get_search_diagnostics(search_context_id)
        if selection_diagnostics is not None:
            result["search_diagnostics"] = selection_diagnostics
        response_text = self._format_json(result)
        if isinstance(search_context_id, str):
            self._record_selection_correction(search_context_id, skill)

        return [TextContent(type="text", text=response_text)]

    @staticmethod
    def _numeric_score(score: Any) -> Optional[float]:
        if not isinstance(score, Real) or isinstance(score, bool):
            return None
        try:
            numeric_score = float(score)
        except (OverflowError, TypeError, ValueError):
            return None
        return numeric_score if math.isfinite(numeric_score) else None

    @classmethod
    def _valid_score(cls, score: Any) -> Optional[float]:
        numeric_score = cls._numeric_score(score)
        return round(numeric_score, 2) if numeric_score is not None else None

    def _remember_search_context(
        self,
        query: str,
        results: List[SearchResult],
        ambiguous: bool,
        score_margin: Optional[float],
        top_candidates: List[Dict[str, Any]],
    ) -> str:
        now = time.monotonic()
        context_id = secrets.token_urlsafe(18)
        score_by_id = {
            result.skill_id: self._numeric_score(getattr(result, "score", None))
            for result in results
        }
        top = results[0]
        with self._search_context_lock:
            expired = [
                key for key, value in self._search_contexts.items()
                if now - value["created_at"] > _CONTEXT_TTL_SECONDS
            ]
            for key in expired:
                self._search_contexts.pop(key, None)
            while len(self._search_contexts) >= _MAX_SEARCH_CONTEXTS:
                self._search_contexts.pop(next(iter(self._search_contexts)))
            self._search_contexts[context_id] = {
                "created_at": now,
                "query": query,
                "top_pick": {
                    "skill_id": top.skill_id,
                    "name": top.name,
                    "score": self._numeric_score(getattr(top, "score", None)),
                },
                "scores": score_by_id,
                "diagnostics": {
                    "ambiguous": ambiguous,
                    "score_margin": score_margin,
                    "top_candidates": [dict(candidate) for candidate in top_candidates],
                },
            }
        return context_id

    def _get_search_diagnostics(self, context_id: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(context_id, str):
            return None
        with self._search_context_lock:
            context = self._search_contexts.get(context_id)
            if not context or time.monotonic() - context["created_at"] > _CONTEXT_TTL_SECONDS:
                return None
            diagnostics = context.get("diagnostics")
            if not isinstance(diagnostics, dict):
                return None
            return {
                **diagnostics,
                "top_candidates": [dict(candidate) for candidate in diagnostics["top_candidates"]],
            }

    def _record_selection_correction(self, context_id: str, selected_skill: Any) -> None:
        with self._search_context_lock:
            context = self._search_contexts.pop(context_id, None)
        if not context or time.monotonic() - context["created_at"] > _CONTEXT_TTL_SECONDS:
            return

        top_pick = context.get("top_pick")
        if not isinstance(top_pick, dict) or not top_pick.get("skill_id"):
            return
        if top_pick["skill_id"] == selected_skill.id:
            return

        raw_top_score = self._numeric_score(top_pick.get("score"))
        raw_selected_score = self._numeric_score(context.get("scores", {}).get(selected_skill.id))
        score_margin = (
            round(abs(raw_top_score - raw_selected_score), 2)
            if raw_top_score is not None and raw_selected_score is not None
            else None
        )
        event = {
            "event": "skill_selection_correction",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "search_context_id": context_id,
            "query": self._sanitize_query(context.get("query", "")),
            "top_pick": {
                "skill_id": top_pick["skill_id"],
                "name": top_pick.get("name", ""),
                "score": round(raw_top_score, 2) if raw_top_score is not None else None,
            },
            "actual_pick": {
                "skill_id": selected_skill.id,
                "name": selected_skill.name,
                "score": round(raw_selected_score, 2) if raw_selected_score is not None else None,
            },
            "score_margin": score_margin,
        }
        try:
            self._append_correction_event(event)
        except Exception:
            logger.warning("Failed to write skill selection correction event")

    @staticmethod
    def _sanitize_query(query: Any) -> str:
        sanitized = str(query)
        for pattern, replacement in _QUERY_SECRET_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized[:1000]

    def _append_correction_event(self, event: Dict[str, Any]) -> None:
        payload = (json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        self.correction_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._correction_log_lock:
            descriptor = os.open(
                self.correction_log_path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                written = os.write(descriptor, payload)
                if written != len(payload):
                    raise OSError("incomplete correction event write")
            finally:
                os.close(descriptor)

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