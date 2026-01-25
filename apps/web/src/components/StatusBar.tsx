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
  onReconnect
}: {
  status: Status
  hostUrl: string
  connected: boolean
  onHostUrlChange: (value: string) => void
  onReconnect: () => void
}) {
  return (
    <div className="rounded-2xl border border-black/10 bg-white/70 shadow-[0_20px_60px_var(--shadow)] p-4 backdrop-blur">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-1">
          <div className="text-sm uppercase tracking-[0.2em] text-black/50">RapidMCP Host</div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
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
            <div className="text-black/60">Model: {status.model}</div>
            <div className="text-black/60">Tools: {status.toolsCount}</div>
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            className="w-full sm:w-72 rounded-xl border border-black/10 px-3 py-2 text-sm bg-white"
            value={hostUrl}
            onChange={(e) => onHostUrlChange(e.target.value)}
          />
          <button
            className="rounded-xl bg-black text-white px-4 py-2 text-sm"
            onClick={onReconnect}
          >
            {connected ? "Reconnect" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  )
}
