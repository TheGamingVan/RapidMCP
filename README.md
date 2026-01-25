RapidMCP Monorepo

Local run steps

1) Copy .env.example to .env and set GEMINI_API_KEY
2) Start everything (MCP server, Host Service, Web UI)
   Windows: .\start_all.ps1
   Linux: ./start_all.sh

Stop everything
   Windows: .\stop_all.ps1
   Linux: ./stop_all.sh

Linux one-time setup: chmod +x start_all.sh stop_all.sh

Manual start (if needed)
   MCP API server
     Windows: services/mcp-server/run_local.ps1
     Linux: services/mcp-server/run_local.sh
   Host Service
     Windows: services/host-service/run_local.ps1
     Linux: services/host-service/run_local.sh
   Web UI
     cd apps/web
     npm install
     npm run dev

Requirements

- Python 3.11+
- Node.js 18+ for Next.js and for npx filesystem MCP

Tests

- Open http://localhost:3000
- Send: "api.add 2 and 3" or "add 2 and 3" and the agent should call api.add and answer 5
- Upload a file and ask: "Read the first 100 characters of the attached file" and the agent should call fs.read_file
