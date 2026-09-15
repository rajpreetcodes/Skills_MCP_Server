"""Main MCP server implementation."""
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from .registry import SkillRegistry
from .profile_loader import ProfileLoader
from .tools import SkillsTools
from .resources import SkillsResources
from .prompts import SkillsPrompts

# Configure logging to stderr only (stdout is reserved for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class SkillsMCPServer:
    """MCP Server for Claude Skills Library."""

    def __init__(self, config: dict):
        self.config = config
        skill_root = Path(config.get("skill_root", "C:\\Users\\rajpr\\.claude\\skills"))
        profile_dir = Path(config.get("profile_dir", "profiles"))

        self.registry = SkillRegistry(skill_root)
        self.profile_loader = ProfileLoader(profile_dir, self.registry)
        self.tools = SkillsTools(self.registry, self.profile_loader)
        self.resources = SkillsResources(self.registry)
        self.prompts = SkillsPrompts(self.registry, self.profile_loader)

        self.server = Server("skills-mcp-server")
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP protocol handlers using the new API."""

        # Tools
        self.server.add_request_handler(
            "tools/list",
            types.PaginatedRequestParams,
            self._handle_list_tools
        )
        self.server.add_request_handler(
            "tools/call",
            types.CallToolRequestParams,
            self._handle_call_tool
        )

        # Resources
        self.server.add_request_handler(
            "resources/list",
            types.PaginatedRequestParams,
            self._handle_list_resources
        )
        self.server.add_request_handler(
            "resources/read",
            types.ReadResourceRequestParams,
            self._handle_read_resource
        )

        # Prompts
        self.server.add_request_handler(
            "prompts/list",
            types.PaginatedRequestParams,
            self._handle_list_prompts
        )
        self.server.add_request_handler(
            "prompts/get",
            types.GetPromptRequestParams,
            self._handle_get_prompt
        )

    async def _handle_list_tools(self, ctx: Any, params: types.PaginatedRequestParams) -> types.ListToolsResult:
        tools = self.tools.get_tools()
        return types.ListToolsResult(tools=tools)

    async def _handle_call_tool(self, ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = await self.tools.call_tool(params.name, params.arguments or {})
        if isinstance(result, types.CallToolResult):
            return result
        return types.CallToolResult(content=result)

    async def _handle_list_resources(self, ctx: Any, params: types.PaginatedRequestParams) -> types.ListResourcesResult:
        resources = self.resources.get_resources()
        return types.ListResourcesResult(resources=resources)

    async def _handle_read_resource(self, ctx: Any, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
        contents = await self.resources.read_resource(str(params.uri))
        return types.ReadResourceResult(contents=contents)

    async def _handle_list_prompts(self, ctx: Any, params: types.PaginatedRequestParams) -> types.ListPromptsResult:
        prompts = self.prompts.get_prompts()
        return types.ListPromptsResult(prompts=prompts)

    async def _handle_get_prompt(self, ctx: Any, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        return await self.prompts.get_prompt(params.name, params.arguments or {})

    async def run_stdio(self):
        """Run the server over STDIO transport."""
        logger.info("Starting Skills MCP Server (STDIO mode)")
        logger.info(f"Skill root: {self.config.get('skill_root')}")
        logger.info(f"Discovered {len(self.registry._skills)} skills")
        logger.info(f"Loaded {len(self.profile_loader._profiles)} profiles")

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="skills-mcp-server",
                    server_version="0.1.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=None,
                        experimental_capabilities={}
                    )
                )
            )

    def get_stats(self) -> dict:
        """Get server statistics."""
        return {
            "skills": len(self.registry._skills),
            "profiles": len(self.profile_loader._profiles),
            "categories": len(self.registry._category_index),
            "skill_root": str(self.registry.skill_root)
        }


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load configuration from file and environment."""
    import os

    default_config = {
        "skill_root": "C:\\Users\\rajpr\\.claude\\skills",
        "profile_dir": "profiles",
        "transport": "stdio",
        "host": "0.0.0.0",
        "port": 8000,
        "log_level": "INFO",
        "auth_token": None
    }

    # Load from config file if exists
    if config_path and config_path.exists():
        try:
            with open(config_path) as f:
                file_config = json.load(f)
                default_config.update(file_config)
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")

    # Override with environment variables
    env_mapping = {
        "SKILL_ROOT": "skill_root",
        "PROFILE_DIR": "profile_dir",
        "TRANSPORT": "transport",
        "HOST": "host",
        "PORT": "port",
        "LOG_LEVEL": "log_level",
        "AUTH_TOKEN": "auth_token"
    }

    for env_var, config_key in env_mapping.items():
        value = os.environ.get(env_var)
        if value is not None:
            if config_key == "port":
                value = int(value)
            default_config[config_key] = value

    return default_config


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Skills MCP Server")
    parser.add_argument("--config", type=Path, help="Path to config file")
    parser.add_argument("--transport", choices=["stdio", "http"], default=None, help="Transport mode")
    parser.add_argument("--host", default=None, help="HTTP host")
    parser.add_argument("--port", type=int, default=None, help="HTTP port")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.transport:
        config["transport"] = args.transport
    if args.host:
        config["host"] = args.host
    if args.port:
        config["port"] = args.port
    if "port" not in config:
        config["port"] = 8080

    server = SkillsMCPServer(config)

    if config["transport"] == "stdio":
        await server.run_stdio()
    else:
        from .http_server import SkillsHTTPServer
        import uvicorn
        http_srv = SkillsHTTPServer(config)
        u_cfg = uvicorn.Config(
            http_srv.app,
            host=config.get("host", "0.0.0.0"),
            port=int(config.get("port", 8000)),
            log_level="info"
        )
        u_server = uvicorn.Server(u_cfg)
        await u_server.serve()


if __name__ == "__main__":
    asyncio.run(main())