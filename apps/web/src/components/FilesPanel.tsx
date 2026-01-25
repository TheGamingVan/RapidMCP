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
  const handleUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) onUpload(file)
    event.target.value = ""
  }

  return (
    <div className="rounded-2xl border border-black/10 bg-white/70 shadow-[0_20px_60px_var(--shadow)] p-4 backdrop-blur">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm uppercase tracking-[0.2em] text-black/50">Files</div>
          <div className="text-xs text-black/40">Attach files for fs tools</div>
        </div>
        <label className="inline-flex items-center justify-center rounded-xl bg-black text-white px-4 py-2 text-sm cursor-pointer">
          Upload
          <input type="file" className="hidden" onChange={handleUpload} />
        </label>
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {files.map((file) => (
          <div key={file.id} className="rounded-xl border border-black/10 bg-white p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-black truncate">{file.name}</div>
                <div className="text-xs text-black/50">{Math.round(file.size / 1024)} KB</div>
              </div>
              <input
                type="checkbox"
                checked={!!selectedFiles[file.id]}
                onChange={() => onToggle(file.id)}
              />
            </div>
            <div className="mt-2 text-[11px] text-black/40 break-all">{file.uri}</div>
            <button
              className="mt-3 rounded-lg border border-black/10 px-2 py-1 text-xs"
              onClick={() => onDelete(file.id)}
            >
              Delete
            </button>
          </div>
        ))}
        {files.length === 0 && (
          <div className="text-sm text-black/40">No files yet</div>
        )}
      </div>
    </div>
  )
}
