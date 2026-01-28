import { useMemo, useState } from "react"
import { FileItem } from "@/lib/types"

export default function FilesPanel({
  files,
  selectedFiles,
  onToggle,
  onUpload,
  onDelete
}: {
  files: FileItem[]
  selectedFiles: Record<string, boolean>
  onToggle: (id: string) => void
  onUpload: (file: File) => void
  onDelete: (id: string) => void
}) {
  const [sortKey, setSortKey] = useState<"name" | "size" | "created">("name")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")

  const handleUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) onUpload(file)
    event.target.value = ""
  }

  const sorted = useMemo(() => {
    const next = [...files]
    next.sort((a, b) => {
      let av: string | number = ""
      let bv: string | number = ""
      if (sortKey === "name") {
        av = a.name.toLowerCase()
        bv = b.name.toLowerCase()
      } else if (sortKey === "size") {
        av = a.size
        bv = b.size
      } else {
        av = Date.parse(a.created) || 0
        bv = Date.parse(b.created) || 0
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1
      if (av > bv) return sortDir === "asc" ? 1 : -1
      return 0
    })
    return next
  }, [files, sortKey, sortDir])

  const handleSort = (key: "name" | "size" | "created") => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(key)
    setSortDir("asc")
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    const kb = bytes / 1024
    if (kb < 1024) return `${kb.toFixed(1)} KB`
    const mb = kb / 1024
    if (mb < 1024) return `${mb.toFixed(1)} MB`
    const gb = mb / 1024
    return `${gb.toFixed(2)} GB`
  }

  return (
    <div className="panel p-6 h-full min-h-0 flex flex-col">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-800">Select files</div>
          <div className="text-sm text-slate-500">Files from the data folder.</div>
        </div>
        <label className="btn">
          Upload Files
          <input type="file" className="hidden" onChange={handleUpload} />
        </label>
      </div>

      <div className="mt-6 overflow-auto flex-1 min-h-0">
        <div className="min-w-[640px]">
          <div className="grid grid-cols-[32px_1.6fr_0.6fr_0.8fr_90px] gap-3 px-3 py-2 text-xs uppercase tracking-[0.18em] text-slate-400">
            <div />
            <button className="text-left" onClick={() => handleSort("name")}>Name</button>
            <button className="text-left" onClick={() => handleSort("size")}>Size</button>
            <button className="text-left" onClick={() => handleSort("created")}>Modified</button>
            <div>Action</div>
          </div>
          <div className="mt-2 space-y-2">
            {sorted.map((file) => (
              <div key={file.id} className="grid grid-cols-[32px_1.6fr_0.6fr_0.8fr_90px] gap-3 items-center rounded-xl border border-slate-200 bg-white px-3 py-2">
                <input
                  type="checkbox"
                  checked={!!selectedFiles[file.id]}
                  onChange={() => onToggle(file.id)}
                />
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-slate-800 truncate">{file.name}</div>
                  <div className="text-[11px] text-slate-400 truncate">{file.uri}</div>
                </div>
                <div className="text-sm text-slate-600">{formatSize(file.size)}</div>
                <div className="text-sm text-slate-600">{new Date(file.created).toLocaleString()}</div>
                <button className="btn-ghost" onClick={() => onDelete(file.id)}>Delete</button>
              </div>
            ))}
            {sorted.length === 0 && (
              <div className="text-sm text-slate-400 px-3">No files found in data folder.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
