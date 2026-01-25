import { ToolEvent } from "@/lib/types"

export default function ToolActivity({ events }: { events: ToolEvent[] }) {
  return (
    <div className="rounded-2xl border border-black/10 bg-white/70 shadow-[0_20px_60px_var(--shadow)] p-4 backdrop-blur">
      <div className="text-sm uppercase tracking-[0.2em] text-black/50">Tool Activity</div>
      <div className="mt-4 space-y-3 max-h-[420px] overflow-auto">
        {events.map((e) => (
          <div key={e.callId} className="rounded-xl border border-black/10 bg-white px-3 py-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">{e.name}</div>
              <div className="text-xs uppercase tracking-[0.2em] text-black/40">{e.status}</div>
            </div>
            <div className="mt-2 h-2 rounded-full bg-black/10">
              <div className="h-2 rounded-full bg-[var(--mint)]" style={{ width: `${Math.floor((e.progress || 0) * 100)}%` }} />
            </div>
            {e.message && <div className="mt-2 text-xs text-black/60">{e.message}</div>}
            {e.error && <div className="mt-2 text-xs text-[var(--rose)]">{e.error}</div>}
          </div>
        ))}
        {events.length === 0 && (
          <div className="text-sm text-black/40">No tool calls yet</div>
        )}
      </div>
    </div>
  )
}
