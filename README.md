# Skills MCP Server

An MCP (Model Context Protocol) server that exposes your Claude Skills library as a discoverable, searchable, and composable skill registry. Designed for seamless integration with **Tasklet** (via HTTP/SSE) and local MCP hosts like **OpenCode**, **Claude Desktop**, and **Cursor** (via STDIO).

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
                        SKILL SOURCE (Canonical)
                    C:\Users\rajpr\.claude\skills
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       ┌─────────────┐                   ┌─────────────┐
       │  LOCAL MODE │                   │ REMOTE MODE │
       │  (STDIO)    │                   │  (HTTP+SSE) │
       └──────┬──────┘                   └──────┬──────┘
              │                                 │
       ┌──────┴──────┐                   ┌──────┴──────┐
       ▼             ▼                   ▼             ▼
   OpenCode    Claude Desktop        Tasklet      Other MCP
   Cursor      Other Local           Cloud         Hosts
   Hosts       Hosts                 Agent
```

## Features

- **Dynamic Discovery**: Automatically finds all skills in your skills directory
- **Smart Search**: Natural language search across names, descriptions, tags, triggers, and categories
- **Multi-Skill Loading**: Retrieve multiple skills at once for complex tasks
- **Profiles/Bundles**: Composable skill profiles for common workflows (product-builder, senior-engineer, researcher, designer)
- **MCP Native**: Full support for Tools, Resources, and Prompts
- **Dual Transport**: STDIO for local, HTTP+SSE for remote (Tasklet)
- **Secure**: Optional Bearer token auth for remote deployments
- **No Duplication**: Reads your existing skills in-place; no copying required

## Quick Start

### 1. Local Development (STDIO)

```bash
cd L:\My Innovations\Skills_MCP_Server
pip install -e .
python -m src.server --transport stdio
```

**OpenCode Configuration** (`~/.opencode/config.json` or project `.opencode/config.json`):

```json
{
  "mcp": {
    "servers": {
      "skills": {
        "command": "python",
        "args": ["-m", "src.server", "--transport", "stdio"],
        "cwd": "L:/My Innovations/Skills_MCP_Server"
      }
    }
  }
}
```

**Claude Desktop Configuration** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "skills": {
      "command": "python",
      "args": ["-m", "src.server", "--transport", "stdio"],
      "cwd": "L:/My Innovations/Skills_MCP_Server"
    }
  }
}
```

### 2. Remote Deployment for Tasklet (HTTP+SSE)

**Option A: Docker (Recommended)**

```bash
# Build
docker build -t skills-mcp-server L:\My Innovations\Skills_MCP_Server

# Run (mount your skills directory)
docker run -d \
  --name skills-mcp \
  -p 8000:8000 \
  -v "C:\Users\rajpr\.claude\skills:/skills:ro" \
  -e SKILL_ROOT=/skills \
  -e AUTH_TOKEN="your-secure-token-here" \
  -e TRANSPORT=http \
  skills-mcp-server
```

### 2. Remote / HTTP Mode (HTTP+SSE)

```bash
cd L:\My Innovations\Skills_MCP_Server
python -m src.server --transport http --host 0.0.0.0 --port 8080
```

**Connection Details:**

- **Transport**: SSE (Server-Sent Events)
- **SSE URL**: `http://localhost:8080/mcp/sse` (or `http://localhost:8080/mcp/sse?token=your-token` if auth enabled)
- **Messages Endpoint**: `/mcp/messages` (advertised dynamically via SSE)
- **Health Check**: `http://localhost:8080/health`
- **Headers**: `Authorization: Bearer <AUTH_TOKEN>` (optional)

## MCP Capabilities

### Tools

| Tool | Purpose |
|------|---------|
| `list_skills` | Browse skill catalog with pagination & category filter |
| `search_skills` | Natural language search for relevant skills |
| `get_skill` | Load full instructions for a single skill |
| `get_skills` | Batch load multiple skills efficiently |
| `list_profiles` | List available skill profiles/bundles |
| `get_profile` | View profile definition and resolved skills |
| `resolve_profile` | Get flat list of skill IDs from a profile (supports stages) |
| `refresh_skills` | Reload registry after adding/removing skills |
| `get_categories` | List all skill categories |
| `get_skill_stats` | Registry statistics |

### Resources

| URI Pattern | Description |
|-------------|-------------|
| `skill://list` | Complete skill catalog as JSON |
| `skill://categories` | All categories with counts |
| `skill://{skill-id}` | Full skill content as Markdown |
| `skill://{skill-id}/{file}` | Supporting files (references, data) |

### Prompts

| Prompt | Purpose |
|--------|---------|
| `activate_skill` | Load single skill with optional context |
| `activate_skills` | Load multiple skills with clear boundaries |
| `activate_profile` | Load entire profile (resolves nested profiles) |
| `suggest_skills` | Get AI recommendations for a task description |

## Usage Examples

### Agent Workflow: "Design a polished SaaS dashboard"

```python
# 1. Agent searches for relevant skills
results = search_skills("design polished dashboard ui ux")
# → Returns: ui-ux-pro-max, impeccable, choosing-design-styles, design-consultation

# 2. Agent loads top matches
skills = get_skills(["ui-ux-pro-max.ui-ux-pro-max", "impeccable.impeccable", ...])
# → Returns full instructions for each skill, clearly separated

# 3. Agent applies combined expertise to the task
```

### Agent Workflow: "Build a secure production API"

```python
# Use profile for structured workflow
profile = resolve_profile("senior-engineer")
# → Returns: [investigate, diagnose, plan-eng-review, ponytail, tdd, review, cso, ...]

# Or load specific stages
research_skills = resolve_profile("product-builder", stage="research")
impl_skills = resolve_profile("product-builder", stage="implementation")
```

### Using Profiles

```yaml
# profiles/product-builder.yaml
name: product-builder
stages:
  research:
    - research
    - research-deep
  design:
    - ui-ux-pro-max
    - impeccable
  implementation:
    - ponytail
    - tdd
  validation:
    - qa
    - review
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SKILL_ROOT` | Path to skills directory | `C:\Users\rajpr\.claude\skills` |
| `PROFILE_DIR` | Profiles directory | `profiles` |
| `TRANSPORT` | `stdio` or `http` | `stdio` |
| `HOST` | HTTP bind address | `0.0.0.0` |
| `PORT` | HTTP port | `8080` |
| `LOG_LEVEL` | Log level | `INFO` |
| `AUTH_TOKEN` | Bearer token for HTTP auth | (none) |

### Config File (`config.json`)

```json
{
  "skill_root": "C:\\Users\\rajpr\\.claude\\skills",
  "profile_dir": "profiles",
  "transport": "stdio",
  "host": "0.0.0.0",
  "port": 8080,
  "log_level": "INFO",
  "auth_token": null
}
```

## Adding Skills

Simply add a new directory under `C:\Users\rajpr\.claude\skills\` with a `SKILL.md` file:

```
skills/
  my-new-skill/
    SKILL.md          # Required: frontmatter + instructions
    references/       # Optional: supporting files
      guide.md
      data.json
```

Then call `refresh_skills` tool or restart the server.

**Skill Frontmatter Example:**

```yaml
---
name: my-skill
description: What this skill does
category: ui-ux
version: "1.0.0"
tags: [design, components]
triggers: ["design a button", "create component"]
allowed-tools: [Read, Write, Bash]
license: MIT
---
# My Skill

Instructions here...
```

## Adding Profiles

Create a YAML file in `profiles/`:

```yaml
# profiles/my-workflow.yaml
name: my-workflow
description: My custom workflow
skills:
  - skill-one
  - skill-two
profiles:
  - other-profile  # Nested profile
stages:
  phase1:
    - skill-one
  phase2:
    - skill-two
```

## Remote Deployment Architecture

### For Tasklet (Cloud)

Since Tasklet runs in the cloud, it cannot access your local Windows filesystem. The remote server must have access to the skill content.

**Recommended Approach:**

1. **Git-backed skills**: Push `C:\Users\rajpr\.claude\skills` to a private Git repo
2. **CI/CD sync**: On push, CI builds Docker image with skills embedded OR deploys to server that clones the repo
3. **Server mounts**: Docker volume or persistent disk with skills content

```
Git Repo (skills) → CI/CD → Docker Image → Cloud Run / K8s / VM
                                                    ↓
                                              Tasklet connects
```

**Docker with Embedded Skills:**

```dockerfile
# In Dockerfile, copy skills at build time
COPY skills/ /skills/
```

**Or Runtime Sync (for frequent updates):**

```bash
# In container startup script
git clone https://github.com/you/skills.git /skills
# Then run server with SKILL_ROOT=/skills
```

### Authentication

**Always use `AUTH_TOKEN` for remote deployments:**

```bash
# Generate secure token
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Set in environment
export AUTH_TOKEN="generated-token-here"
```

Tasklet connection must include: `Authorization: Bearer <token>`

## Testing

```bash
# Run all tests
cd L:\My Innovations\Skills_MCP_Server
pytest tests/ -v

# Run specific test file
pytest tests/test_registry.py -v
pytest tests/test_search.py -v
pytest tests/test_profiles.py -v
pytest tests/test_server.py -v
```

## MCP Inspector Validation

```bash
# Install inspector
npm install -g @modelcontextprotocol/inspector

# Test STDIO mode
npx @modelcontextprotocol/inspector python -m src.server --transport stdio

# Test HTTP mode (in separate terminal)
python -m src.server --transport http --port 8080
# Then in inspector: connect to http://localhost:8080/mcp/sse
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No skills found" | Check `SKILL_ROOT` path exists and has `SKILL.md` files |
| "Connection refused" | Verify server is running, port accessible, firewall allows traffic |
| "401 Unauthorized" | Check `AUTH_TOKEN` matches in server env and connection headers |
| "Skill not found" | Run `refresh_skills` tool after adding skills |
| "Circular dependency" | Check profile YAML for circular `profiles:` references |
| STDIO: garbled output | Ensure no `print()` to stdout; all logging goes to stderr |

## Security Considerations

- **Never expose HTTP without auth** in production
- **Use HTTPS** behind reverse proxy (nginx, Caddy, Cloudflare Tunnel)
- **Restrict network access** to authorized client IPs only
- **Read-only skill mount** (`:ro` in Docker)
- **No arbitrary code execution**: server only reads skill files

## Future Extensibility

The architecture supports adding without rewrite:
- Git-based skill sources (remote repos)
- Semantic/vector search (embeddings)
- Skill versioning & dependencies
- Multi-user permissions
- Skill marketplace
- OAuth/OIDC integration
- Multi-repository aggregation

## License

MIT: See individual skill licenses in their respective directories.