# RapidMCP

RapidMCP is a local, multi-service app that combines:

- a web chat UI,
- a Host Service that orchestrates tool calls,
- an MCP server generated from an OpenAPI spec,
- and optional filesystem MCP tools (via `npx @modelcontextprotocol/server-filesystem`).

It is designed for tool-driven workflows against the RapidPipeline API, with Gemini used for planning and response generation.

## Architecture

- `apps/web` (`http://localhost:3000`): React + Vite frontend.
- `services/host-service` (`http://localhost:8080`): FastAPI backend that:
  - exposes `/status`, `/tools`, `/files`, `/config`,
  - manages uploads and chat sessions,
  - connects to Gemini,
  - calls MCP tools through HTTP and stdio.
- `services/mcp-server` (`http://localhost:8000/mcp`): FastMCP HTTP endpoint built from `services/mcp-server/openapi.yml`.

## Prerequisites

- Python `3.11+`
- Node.js `20.x` (required by `apps/web/package.json`)
- `npm`/`npx` available in PATH

## Configuration

The repo reads runtime settings from:

- `.env` (root)
- `config/api_config.json` (written/read by Host Service and the UI)

### `.env` example

Create/update `.env` in the repository root:

```env
HOST_PORT=8080
MCP_API_URL=http://localhost:8000/mcp/
FILE_STORE_DIR=./data
FS_MCP_ENABLED=true
FS_ALLOWED_DIRS=./data
API_BASE_URL=https://api.rapidpipeline.com
FS_NPX_COMMAND=npx
FS_MCP_PACKAGE=@modelcontextprotocol/server-filesystem
```

Set credentials in the UI (recommended) or in `config/api_config.json`:

- `apiBaseUrl`
- `bearerToken`
- `geminiApiKey`
- `geminiModel`

## Install and Start

### One-command startup

From the repository root:

- Windows:
  - `.\start_all.ps1`
- Linux/macOS:
  - `chmod +x start_all.sh stop_all.sh`
  - `./start_all.sh`

This starts all services:

- MCP Server on `8000`
- Host Service on `8080`
- Web UI on `3000`

### Stop all services

- Windows: `.\stop_all.ps1`
- Linux/macOS: `./stop_all.sh`

## Manual Start (optional)

If you want to run services individually:

### 1) MCP server

- Windows: `services/mcp-server/run_local.ps1`
- Linux/macOS: `services/mcp-server/run_local.sh`

### 2) Host service

- Windows: `services/host-service/run_local.ps1`
- Linux/macOS: `services/host-service/run_local.sh`

### 3) Web UI

```bash
cd apps/web
npm install
npm run dev
```

## How to Use

1. Open `http://localhost:3000`.
2. In the config panel, set:
   - Host URL (default `http://localhost:8080`)
   - API Base URL + Bearer Token
   - Gemini API Key + Model
3. Send chat instructions in natural language.
4. Upload files in the UI when you want filesystem tool access (read/write/list/delete).
5. Monitor live tool execution in the tool activity panel.

### Example prompts

- `List the latest rapid models and summarize their names.`
- `Upload file X and optimize it.`
- `Show available API tools and explain which one to use for optimization.`

## Service Endpoints

### Host Service (`:8080`)

- `GET /health`
- `GET /status`
- `GET /tools`
- `GET /files`
- `POST /upload`
- `GET /config`
- `POST /config`
- `GET /gemini/models`
- `WS /ws`

### MCP Server (`:8000`)

- `GET /health`
- `GET /info`
- MCP endpoint: `/mcp`

## Troubleshooting

- UI cannot connect:
  - verify Host Service is running on `http://localhost:8080`.
- No tools available:
  - verify MCP Server is running on `http://localhost:8000`.
  - verify `MCP_API_URL` points to `/mcp`.
- Filesystem tools missing:
  - verify `FS_MCP_ENABLED=true`.
  - verify Node.js and `npx` are installed.
- Gemini models list empty:
  - verify `geminiApiKey` is set and valid.
