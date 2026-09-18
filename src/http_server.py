"""HTTP transport server for remote MCP access (Tasklet, etc.)."""
import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from mcp import types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, Resource, Prompt

from .registry import SkillRegistry
from .profile_loader import ProfileLoader
from .tools import SkillsTools
from .resources import SkillsResources
from .prompts import SkillsPrompts

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window in-memory rate limiter per client IP address."""

    def __init__(self, requests_per_minute: int = 60, enabled: bool = True):
        self.requests_per_minute = requests_per_minute
        self.enabled = enabled
        self._clients: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, client_id: str) -> Tuple[bool, int, int]:
        """Check if request is allowed. Returns (allowed, remaining, retry_after)."""
        if not self.enabled or self.requests_per_minute <= 0:
            return True, self.requests_per_minute, 0

        now = time.time()
        window_start = now - 60.0

        async with self._lock:
            history = self._clients.get(client_id, [])
            history = [t for t in history if t > window_start]

            if len(history) >= self.requests_per_minute:
                retry_after = int(history[0] - window_start) + 1
                self._clients[client_id] = history
                return False, 0, max(1, retry_after)

            history.append(now)
            self._clients[client_id] = history
            remaining = self.requests_per_minute - len(history)
            return True, remaining, 0

    def reset(self):
        """Clear rate limiter history."""
        self._clients.clear()


class SkillsHTTPServer:
    """MCP Server with HTTP/SSE transport for remote access."""

    def __init__(self, config: dict):
        self.config = config
        skill_root = Path(config.get("skill_root", "C:\\Users\\rajpr\\.claude\\skills"))
        profile_dir = Path(config.get("profile_dir", "profiles"))

        self.registry = SkillRegistry(skill_root)
        self.profile_loader = ProfileLoader(profile_dir, self.registry)
        self.tools = SkillsTools(self.registry, self.profile_loader)
        self.resources = SkillsResources(self.registry)
        self.prompts = SkillsPrompts(self.registry, self.profile_loader)

        self.mcp_server = Server("skills-mcp-server")
        self._register_mcp_handlers()

        # HTTP app
        self.app = FastAPI(
            title="Skills MCP Server",
            description="MCP server for Claude Skills Library - Remote access for Tasklet and other hosts",
            version="0.1.0"
        )
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Rate limiting
        self.rate_limiter = RateLimiter(
            requests_per_minute=int(config.get("rate_limit_per_minute", 60)),
            enabled=bool(config.get("rate_limit_enabled", True))
        )
        self._setup_rate_limiting()
        self._setup_auth()
        self._setup_http_routes()

        # SSE transport
        self.sse_transport = SseServerTransport("/mcp/messages")

    def _setup_rate_limiting(self):
        """Setup rate limiting middleware on FastAPI."""
        from starlette.responses import JSONResponse

        @self.app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            if not self.rate_limiter.enabled:
                return await call_next(request)

            # Health check endpoint bypasses rate limiting
            if request.url.path == "/health":
                return await call_next(request)

            client_id = request.client.host if request.client else "127.0.0.1"
            allowed, remaining, retry_after = await self.rate_limiter.is_allowed(client_id)

            if not allowed:
                return JSONResponse(
                    content={"detail": "Rate limit exceeded. Please retry later."},
                    status_code=429,
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.rate_limiter.requests_per_minute),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(retry_after)
                    }
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self.rate_limiter.requests_per_minute)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response

    def _register_mcp_handlers(self):
        """Register MCP protocol handlers using add_request_handler."""
        self.mcp_server.add_request_handler(
            "tools/list",
            types.PaginatedRequestParams,
            self._handle_list_tools
        )
        self.mcp_server.add_request_handler(
            "tools/call",
            types.CallToolRequestParams,
            self._handle_call_tool
        )
        self.mcp_server.add_request_handler(
            "resources/list",
            types.PaginatedRequestParams,
            self._handle_list_resources
        )
        self.mcp_server.add_request_handler(
            "resources/read",
            types.ReadResourceRequestParams,
            self._handle_read_resource
        )
        self.mcp_server.add_request_handler(
            "prompts/list",
            types.PaginatedRequestParams,
            self._handle_list_prompts
        )
        self.mcp_server.add_request_handler(
            "prompts/get",
            types.GetPromptRequestParams,
            self._handle_get_prompt
        )

    async def _handle_list_tools(self, ctx: any, params: types.PaginatedRequestParams) -> types.ListToolsResult:
        tools = self.tools.get_tools()
        return types.ListToolsResult(tools=tools)

    async def _handle_call_tool(self, ctx: any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = await self.tools.call_tool(params.name, params.arguments or {})
        if isinstance(result, types.CallToolResult):
            return result
        return types.CallToolResult(content=result)

    async def _handle_list_resources(self, ctx: any, params: types.PaginatedRequestParams) -> types.ListResourcesResult:
        resources = self.resources.get_resources()
        return types.ListResourcesResult(resources=resources)

    async def _handle_read_resource(self, ctx: any, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
        contents = await self.resources.read_resource(str(params.uri))
        return types.ReadResourceResult(contents=contents)

    async def _handle_list_prompts(self, ctx: any, params: types.PaginatedRequestParams) -> types.ListPromptsResult:
        prompts = self.prompts.get_prompts()
        return types.ListPromptsResult(prompts=prompts)

    async def _handle_get_prompt(self, ctx: any, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        return await self.prompts.get_prompt(params.name, params.arguments or {})

    def _setup_auth(self):
        """Setup authentication dependency."""
        import os
        import secrets

        self.auth_token = self.config.get("auth_token") or os.environ.get("AUTH_TOKEN")
        if self.config.get("transport") == "http" and not self.auth_token:
            logger.warning("AUTH_TOKEN is not configured for HTTP transport. Authentication is disabled.")

        async def verify_token(request: Request):
            if self.auth_token:
                token = None
                auth_header = request.headers.get("Authorization")
                if auth_header and auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()
                elif "token" in request.query_params:
                    token = request.query_params.get("token")

                if not token:
                    raise HTTPException(status_code=401, detail="Missing or invalid Authorization header or token query parameter")
                if not secrets.compare_digest(token, self.auth_token):
                    raise HTTPException(status_code=403, detail="Invalid token")
            return True

        self.auth_dependency = verify_token

    def _setup_http_routes(self):
        """Setup HTTP routes."""
        from starlette.responses import Response

        @self.app.get("/health")
        async def health_check():
            return {
                "status": "healthy",
                "skills": len(self.registry._skills),
                "profiles": len(self.profile_loader._profiles),
                "version": "0.1.0"
            }

        @self.app.get("/")
        async def root():
            return {
                "name": "Skills MCP Server",
                "description": "MCP server for Claude Skills Library",
                "version": "0.1.0",
                "endpoints": {
                    "mcp_sse": "/mcp/sse",
                    "mcp_messages": "/mcp/messages",
                    "health": "/health",
                    "stats": "/stats"
                }
            }

        @self.app.get("/stats")
        async def stats(auth: bool = Depends(self.auth_dependency)):
            return self.get_stats()

        # MCP SSE endpoint
        @self.app.get("/mcp/sse")
        async def mcp_sse(request: Request, auth: bool = Depends(self.auth_dependency)):
            """SSE endpoint for MCP connection."""
            async with self.sse_transport.connect_sse(
                request.scope,
                request.receive,
                request._send
            ) as (read_stream, write_stream):
                await self.mcp_server.run(
                    read_stream,
                    write_stream,
                    self.mcp_server.create_initialization_options()
                )
            return Response()

        # MCP messages endpoint (for SSE)
        @self.app.post("/mcp/messages")
        async def mcp_messages(request: Request, auth: bool = Depends(self.auth_dependency)):
            """Handle MCP messages via POST (for SSE transport)."""
            await self.sse_transport.handle_post_message(request.scope, request.receive, request._send)
            return Response()

        # Direct JSON-RPC endpoint (alternative for clients that don't support SSE)
        @self.app.post("/mcp/rpc")
        async def mcp_rpc(request: Request, auth: bool = Depends(self.auth_dependency)):
            """Direct JSON-RPC endpoint for MCP."""
            body = await request.json()
            return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "Use SSE endpoint for MCP"}}

    def get_stats(self) -> dict:
        """Get server statistics."""
        return {
            "skills": len(self.registry._skills),
            "profiles": len(self.profile_loader._profiles),
            "categories": len(self.registry._category_index),
            "skill_root": str(self.registry.skill_root),
            "transport": "http+sse",
            "rate_limiting": {
                "enabled": self.rate_limiter.enabled,
                "limit_per_minute": self.rate_limiter.requests_per_minute
            }
        }

    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """Run the HTTP server."""
        logger.info(f"Starting Skills MCP Server (HTTP+SSE mode) on {host}:{port}")
        logger.info(f"Skill root: {self.config.get('skill_root')}")
        logger.info(f"Discovered {len(self.registry._skills)} skills")
        logger.info(f"Loaded {len(self.profile_loader._profiles)} profiles")
        if self.auth_token:
            logger.info("Authentication: ENABLED (Bearer token)")
        else:
            logger.warning("Authentication: DISABLED - not recommended for production")

        uvicorn.run(self.app, host=host, port=port, log_level="info")


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load configuration from file and environment."""
    import os

    default_config = {
        "skill_root": "C:\\Users\\rajpr\\.claude\\skills",
        "profile_dir": "profiles",
        "transport": "http",
        "host": "0.0.0.0",
        "port": 8000,
        "log_level": "INFO",
        "auth_token": None,
        "rate_limit_enabled": True,
        "rate_limit_per_minute": 60
    }

    if config_path and config_path.exists():
        try:
            with open(config_path) as f:
                file_config = json.load(f)
                default_config.update(file_config)
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")

    env_mapping = {
        "SKILL_ROOT": "skill_root",
        "PROFILE_DIR": "profile_dir",
        "TRANSPORT": "transport",
        "HOST": "host",
        "PORT": "port",
        "LOG_LEVEL": "log_level",
        "AUTH_TOKEN": "auth_token",
        "RATE_LIMIT_ENABLED": "rate_limit_enabled",
        "RATE_LIMIT_PER_MINUTE": "rate_limit_per_minute"
    }

    for env_var, config_key in env_mapping.items():
        value = os.environ.get(env_var)
        if value is not None:
            if config_key in ("port", "rate_limit_per_minute"):
                value = int(value)
            elif config_key == "rate_limit_enabled":
                value = str(value).lower() not in ("false", "0", "no", "off")
            default_config[config_key] = value

    return default_config


def main():
    """Main entry point for HTTP server."""
    import argparse

    parser = argparse.ArgumentParser(description="Skills MCP Server (HTTP)")
    parser.add_argument("--config", type=Path, help="Path to config file")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    args = parser.parse_args()

    config = load_config(args.config)
    config["host"] = args.host
    config["port"] = args.port

    server = SkillsHTTPServer(config)
    server.run(args.host, args.port)


if __name__ == "__main__":
    main()