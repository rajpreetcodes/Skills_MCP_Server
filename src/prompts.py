"""MCP Prompts for the skills server."""
from typing import List, Optional
from mcp.types import Prompt, PromptArgument, GetPromptResult, PromptMessage, TextContent
from .registry import SkillRegistry
from .profile_loader import ProfileLoader


class SkillsPrompts:
    """MCP prompt implementations."""

    def __init__(self, registry: SkillRegistry, profile_loader: ProfileLoader):
        self.registry = registry
        self.profile_loader = profile_loader

    def get_prompts(self) -> List[Prompt]:
        """Return all available MCP prompts."""
        return [
            Prompt(
                name="activate_skill",
                description="Activate a single skill by ID. Returns the skill's instructions formatted for the agent.",
                arguments=[
                    PromptArgument(
                        name="skill_id",
                        description="Skill ID to activate (e.g., 'ui-ux-pro-max.ui-ux-pro-max')",
                        required=True
                    ),
                    PromptArgument(
                        name="context",
                        description="Optional context about the task for the skill",
                        required=False
                    )
                ]
            ),
            Prompt(
                name="activate_skills",
                description="Activate multiple skills by their IDs. Returns all skills' instructions combined with clear boundaries.",
                arguments=[
                    PromptArgument(
                        name="skill_ids",
                        description="Comma-separated list of skill IDs",
                        required=True
                    ),
                    PromptArgument(
                        name="context",
                        description="Optional context about the task",
                        required=False
                    )
                ]
            ),
            Prompt(
                name="activate_profile",
                description="Activate a profile (bundle of skills). Resolves the profile and returns all constituent skills.",
                arguments=[
                    PromptArgument(
                        name="profile_name",
                        description="Profile name (e.g., 'product-builder', 'senior-engineer')",
                        required=True
                    ),
                    PromptArgument(
                        name="stage",
                        description="Optional: activate only a specific stage (e.g., 'research', 'design', 'implementation')",
                        required=False
                    ),
                    PromptArgument(
                        name="context",
                        description="Optional context about the task",
                        required=False
                    )
                ]
            ),
            Prompt(
                name="suggest_skills",
                description="Get skill suggestions for a task description. Returns recommended skills with reasoning.",
                arguments=[
                    PromptArgument(
                        name="task",
                        description="Description of the task or goal",
                        required=True
                    )
                ]
            )
        ]

    async def get_prompt(self, name: str, arguments: dict) -> GetPromptResult:
        """Execute a prompt by name."""
        if name == "activate_skill":
            return await self._activate_skill(arguments)
        elif name == "activate_skills":
            return await self._activate_skills(arguments)
        elif name == "activate_profile":
            return await self._activate_profile(arguments)
        elif name == "suggest_skills":
            return await self._suggest_skills(arguments)
        else:
            return GetPromptResult(
                description=f"Unknown prompt: {name}",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"Unknown prompt: {name}"))]
            )

    async def _activate_skill(self, args: dict) -> GetPromptResult:
        skill_id = args.get("skill_id", "")
        context = args.get("context", "")

        skill = self.registry.get_skill(skill_id)
        if not skill:
            return GetPromptResult(
                description=f"Skill not found: {skill_id}",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"Skill not found: {skill_id}"))]
            )

        content = self._format_skill_for_agent(skill, context)
        return GetPromptResult(
            description=f"Activated skill: {skill.metadata.name}",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=content))]
        )

    async def _activate_skills(self, args: dict) -> GetPromptResult:
        skill_ids_str = args.get("skill_ids", "")
        context = args.get("context", "")

        skill_ids = [s.strip() for s in skill_ids_str.split(",") if s.strip()]
        if not skill_ids:
            return GetPromptResult(
                description="No skill IDs provided",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text="Error: No skill IDs provided"))]
            )

        skills = []
        not_found = []
        for sid in skill_ids:
            skill = self.registry.get_skill(sid)
            if skill:
                skills.append(skill)
            else:
                not_found.append(sid)

        if not skills:
            return GetPromptResult(
                description="No valid skills found",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"No valid skills found. Not found: {not_found}"))]
            )

        content = "ACTIVE SKILLS\n"
        content += "=" * 50 + "\n\n"
        if context:
            content += f"TASK CONTEXT: {context}\n\n"

        for i, skill in enumerate(skills):
            if i > 0:
                content += "\n" + "=" * 50 + "\n\n"
            content += self._format_skill_for_agent(skill, "")

        if not_found:
            content += f"\n\nNOTE: These skills were not found: {', '.join(not_found)}"

        return GetPromptResult(
            description=f"Activated {len(skills)} skills",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=content))]
        )

    async def _activate_profile(self, args: dict) -> GetPromptResult:
        profile_name = args.get("profile_name", "")
        stage = args.get("stage")
        context = args.get("context", "")

        profile = self.profile_loader.get_profile(profile_name)
        if not profile:
            return GetPromptResult(
                description=f"Profile not found: {profile_name}",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"Profile not found: {profile_name}"))]
            )

        try:
            if stage:
                skill_ids = self.profile_loader.get_stage_skills(profile_name, stage)
            else:
                skill_ids = self.profile_loader.resolve_profile(profile_name)
        except Exception as e:
            return GetPromptResult(
                description=f"Error resolving profile: {e}",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"Error resolving profile: {e}"))]
            )

        if not skill_ids:
            return GetPromptResult(
                description=f"Profile '{profile_name}' resolves to no skills",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text=f"Profile '{profile_name}' resolves to no skills"))]
            )

        # Get the skills
        skills = []
        for sid in skill_ids:
            skill = self.registry.get_skill(sid)
            if skill:
                skills.append(skill)

        content = f"ACTIVE PROFILE: {profile.name.upper()}\n"
        content += "=" * 50 + "\n\n"
        content += f"Description: {profile.description}\n"
        if stage:
            content += f"Stage: {stage}\n"
        content += f"Skills ({len(skills)}): {', '.join([s.metadata.name for s in skills])}\n\n"
        if context:
            content += f"TASK CONTEXT: {context}\n\n"

        for i, skill in enumerate(skills):
            if i > 0:
                content += "\n" + "=" * 50 + "\n\n"
            content += self._format_skill_for_agent(skill, "")

        return GetPromptResult(
            description=f"Activated profile: {profile.name} ({len(skills)} skills)",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=content))]
        )

    async def _suggest_skills(self, args: dict) -> GetPromptResult:
        task = args.get("task", "")

        if not task:
            return GetPromptResult(
                description="Task description required",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text="Error: Task description required"))]
            )

        # Search for relevant skills
        results = self.registry.search_skills(task, limit=15)

        if not results:
            return GetPromptResult(
                description="No matching skills found",
                messages=[PromptMessage(role="user", content=TextContent(type="text", text="No matching skills found for this task."))]
            )

        content = f"SKILL SUGGESTIONS FOR: {task}\n"
        content += "=" * 50 + "\n\n"

        for i, r in enumerate(results[:10], 1):
            content += f"{i}. **{r.name}** (`{r.skill_id}`)\n"
            content += f"   Category: {r.category} | Score: {r.score:.1f} | Matched: {', '.join(r.matched_fields)}\n"
            content += f"   {r.description[:150]}...\n"
            if r.tags:
                content += f"   Tags: {', '.join(r.tags[:5])}\n"
            content += "\n"

        content += "\nRECOMMENDATION: Use `activate_skills` with the most relevant skill IDs, or `activate_profile` if a profile matches your workflow."

        return GetPromptResult(
            description=f"Found {len(results)} relevant skills",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=content))]
        )

    def _format_skill_for_agent(self, skill: 'Skill', context: str) -> str:
        """Format a skill for agent consumption with clear boundaries."""
        content = f"===== {skill.metadata.name.upper()} =====\n"
        content += f"Skill ID: {skill.metadata.id}\n"
        content += f"Category: {skill.metadata.category}\n"
        if skill.metadata.triggers:
            content += f"Triggers: {', '.join(skill.metadata.triggers)}\n"
        if context and context.strip():
            content += f"Task Context: {context.strip()}\n"
        content += "\n"
        content += skill.content
        return content