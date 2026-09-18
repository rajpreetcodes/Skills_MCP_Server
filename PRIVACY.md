# Privacy Policy for Skills MCP Server

Last updated: September 18, 2026

Skills MCP Server is an open-source Model Context Protocol (MCP) server developed by Rajpreet Singh Khurana (QuirkSphere / QSP INFOSOLUTIONS PVT LTD). This Privacy Policy explains how data is handled when you run or interact with Skills MCP Server.

## 1. Fundamental Principle: Local-First by Design

Skills MCP Server is designed from the ground up as a local-first engineering utility. It operates directly on your machine or on your self-hosted infrastructure. 

- **No Remote Telemetry**: The server does not contain telemetry, tracking pixels, usage analytics, or error-reporting services that phone home to us or to any third party.
- **No External Data Exfiltration**: Skills, prompts, and tool inputs are evaluated strictly against your local filesystem and within the running process memory.

## 2. Information Handled by the Server

When the server runs, it processes the following data solely to fulfill MCP client requests:

1. **Skill Files and Directories**: The server reads local markdown and YAML files from your designated skills folder (default: `~/.claude/skills`) and profiles folder. This content remains on your local filesystem.
2. **Search Queries and Skill IDs**: Queries submitted by your AI assistant (e.g., natural language search strings for `search_skills`, specific skill identifiers for `get_skill`) are processed locally using in-memory BM25 indexing and keyword matching.
3. **Authentication Credentials**: When running in remote/HTTP transport mode with authentication enabled, incoming bearer tokens are validated in memory using constant-time cryptographic comparison (`secrets.compare_digest`). Tokens are never logged, persisted, or exported.
4. **Client IP Addresses (Rate Limiting)**: In HTTP mode, client IP addresses are temporarily retained in an in-memory sliding window cache solely to enforce rate limits and protect against denial-of-service attempts. These records are never written to disk and expire automatically after sixty seconds.

## 3. Data Storage and Retention

- **Ephemeral In-Memory State**: All skill registries, search indexes, rate limiting tables, and profile mappings exist only in process RAM. Terminating or restarting the server immediately clears all in-memory data.
- **Local Filesystem Only**: The only persisted data is what you place in your local skills directory. The server does not write to external databases, cloud buckets, or remote servers.

## 4. Third-Party Sharing and Disclosures

We do not sell, rent, share, or transfer any user data, search queries, skill contents, or authentication credentials to third parties under any circumstances.

## 5. Security Measures

- **Constant-Time Verification**: Bearer token authentication prevents timing attacks.
- **Input Validation**: All MCP tool calls validate schema types strictly via Pydantic models.
- **Safe Stdio Separation**: Standard I/O communication reserves stdout strictly for framed MCP JSON-RPC protocol messages, routing diagnostics and server logs strictly to stderr.
- **Rate Limiting**: Configurable sliding-window rate limiting prevents resource exhaustion in remote deployments.

## 6. Directory Compliance

This Privacy Policy complies with privacy and security requirements established by:
- Anthropic Claude Desktop and Claude.ai Web MCP directories
- OpenAI MCP integration standards
- M8ven Trust Index criteria

## 7. Contact and Inquiries

If you have questions or concerns regarding this Privacy Policy, you may reach out via:
- GitHub Repository: [https://github.com/rajpreetcodes/Skills_MCP_Server/issues](https://github.com/rajpreetcodes/Skills_MCP_Server/issues)
- Email: quirkcursor@gmail.com
