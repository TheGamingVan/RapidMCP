import { useMemo, useState } from "react"
import { Tool } from "@/lib/types"

export default function Sidebar({ tools }: { tools: Tool[] }) {
  const [query, setQuery] = useState("")
  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim()
    if (!q) return tools
    return tools.filter((t) => t.name.toLowerCase().includes(q))
  }, [tools, query])

  return (
    <div className="rounded-2xl border border-black/10 bg-white/70 shadow-[0_20px_60px_var(--shadow)] p-4 backdrop-blur">
      <div className="text-sm uppercase tracking-[0.2em] text-black/50">Tools</div>
      <input
        className="mt-3 w-full rounded-xl border border-black/10 px-3 py-2 text-sm bg-white"
        placeholder="Search tools"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="mt-4 space-y-2 max-h-[420px] overflow-auto">
        {filtered.map((tool) => (
          <div key={tool.name} className="rounded-xl border border-black/10 bg-white px-3 py-2">
            <div className="text-sm font-semibold text-black">{tool.name}</div>
            <div className="text-xs text-black/60">{tool.description}</div>
            <div className="text-[11px] text-black/40 mt-1">{tool.source}</div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="text-sm text-black/40">No tools</div>
        )}
      </div>
    </div>
  )
}
