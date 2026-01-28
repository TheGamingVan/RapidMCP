import { Status } from "@/lib/types"

const statusColor = (value: string) => {
  if (value === "ok") return "bg-emerald-500"
  return "bg-red-500 ring-2 ring-red-200"
}

export default function StatusBar({
  status,
  hostUrl,
  connected,
  onHostUrlChange,
  onReconnect,
  apiConfig,
  onApiConfigChange,
  onSaveApiConfig,
  isSavingConfig
}: {
  status: Status
  hostUrl: string
  connected: boolean
  onHostUrlChange: (value: string) => void
  onReconnect: () => void
  apiConfig: { apiBaseUrl: string; bearerToken: string }
  onApiConfigChange: (value: Partial<{ apiBaseUrl: string; bearerToken: string }>) => void
  onSaveApiConfig: () => void
  isSavingConfig: boolean
}) {
  return (
    <div className="w-full border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-xl bg-emerald-500 text-white grid place-items-center font-bold">R</div>
            <div className="text-lg font-semibold">RapidMCP</div>
          </div>
          <div className="hidden lg:flex items-center gap-4 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${statusColor(status.gemini)}`} />
              <span>Gemini</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${statusColor(status.mcpApi)}`} />
              <span>MCP API</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${statusColor(status.fsMcp)}`} />
              <span>FS MCP</span>
            </div>
            <div>Model: {status.model}</div>
            <div>Tools: {status.toolsCount}</div>
          </div>
        </div>
        <div className="flex flex-col gap-3 sm:w-[360px]">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <input
              className="input sm:w-72"
              value={hostUrl}
              onChange={(e) => onHostUrlChange(e.target.value)}
              placeholder="Host URL"
            />
            <button className="btn-primary" onClick={onReconnect}>
              {connected ? "Reconnect" : "Connect"}
            </button>
          </div>
          <div className="grid grid-cols-1 gap-2">
            <input
              className="input"
              value={apiConfig.apiBaseUrl}
              onChange={(e) => onApiConfigChange({ apiBaseUrl: e.target.value })}
              placeholder="API Base URL"
            />
            <input
              className="input"
              type="password"
              value={apiConfig.bearerToken}
              onChange={(e) => onApiConfigChange({ bearerToken: e.target.value })}
              placeholder="Bearer Token"
            />
            <button className="btn-primary" onClick={onSaveApiConfig} disabled={isSavingConfig}>
              {isSavingConfig ? "Saving..." : "Save API Config"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
