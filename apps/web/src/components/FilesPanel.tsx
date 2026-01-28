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
    <div className="panel p-6 h-full min-h-0 flex flex-col">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-800">Select files</div>
          <div className="text-sm text-slate-500">Upload or drag & drop files here to process your assets.</div>
        </div>
        <label className="btn">
          Upload Files
          <input type="file" className="hidden" onChange={handleUpload} />
        </label>
      </div>

      <div className="mt-6 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center">
        <div className="mx-auto h-14 w-14 rounded-full border border-slate-200 bg-white grid place-items-center text-slate-400">⬆</div>
        <div className="mt-4 text-sm text-slate-600">Select or drag & drop files here to process your assets.</div>
        <div className="mt-1 text-xs text-slate-400">Available storage: 250GB (0% used)</div>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 overflow-auto flex-1 min-h-0">
        {files.map((file) => (
          <div key={file.id} className="rounded-xl border border-slate-200 bg-white p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-slate-800 truncate">{file.name}</div>
                <div className="text-xs text-slate-500">{Math.round(file.size / 1024)} KB</div>
              </div>
              <input
                type="checkbox"
                checked={!!selectedFiles[file.id]}
                onChange={() => onToggle(file.id)}
              />
            </div>
            <div className="mt-2 text-[11px] text-slate-400 break-all">{file.uri}</div>
            <button
              className="btn-ghost mt-3"
              onClick={() => onDelete(file.id)}
            >
              Delete
            </button>
          </div>
        ))}
        {files.length === 0 && (
          <div className="text-sm text-slate-400">No files yet</div>
        )}
      </div>
    </div>
  )
}
