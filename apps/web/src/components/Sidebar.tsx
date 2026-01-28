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
    <div className="panel p-4 h-full flex flex-col min-h-0">
      <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Tools</div>
      <input
        className="input mt-3"
        placeholder="Search tools"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="mt-4 space-y-2 overflow-auto flex-1 min-h-0">
        {filtered.map((tool) => (
          <div key={tool.name} className="rounded-xl border border-slate-200 bg-white px-3 py-2">
            <div className="text-sm font-semibold text-slate-800">{tool.name}</div>
            <div className="text-xs text-slate-500">{tool.description}</div>
            <div className="text-[11px] text-slate-400 mt-1">{tool.source}</div>
          </div>
        ))}
        {filtered.length === 0 && (
          <div className="text-sm text-slate-400">No tools</div>
        )}
      </div>
    </div>
  )
}
