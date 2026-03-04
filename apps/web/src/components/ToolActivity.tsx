import { useEffect, useRef, useState } from "react"
import { ToolEvent } from "@/lib/types"

export default function ToolActivity({ events }: { events: ToolEvent[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [isHovered, setIsHovered] = useState(false)

  useEffect(() => {
    if (isHovered) return
    const el = scrollRef.current
    if (!el) return
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
  }, [events, isHovered])

  return (
    <div className="panel p-4 h-full min-h-0 flex flex-col min-w-0">
      <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Tool Activity</div>
      <div
        ref={scrollRef}
        className="mt-4 space-y-3 overflow-y-auto overflow-x-auto flex-1 min-h-0 min-w-0"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {events.map((e) => (
          <div key={e.callId} className="rounded-xl border border-slate-200 bg-white px-3 py-2">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-800">{e.name}</div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-slate-400">{e.status}</div>
            </div>
            <div className="mt-2 h-2 rounded-full bg-slate-100">
              <div className="h-2 rounded-full bg-[var(--mint)]" style={{ width: `${Math.floor((e.progress || 0) * 100)}%` }} />
            </div>
            {e.message && <div className="mt-2 text-xs text-slate-500">{e.message}</div>}
            {e.error && <div className="mt-2 text-xs text-[var(--rose)]">{e.error}</div>}
          </div>
        ))}
        {events.length === 0 && (
          <div className="text-sm text-slate-400">No tool calls yet</div>
        )}
      </div>
    </div>
  )
}
