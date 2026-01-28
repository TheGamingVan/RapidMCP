import { ApiConfig } from "@/lib/types"

export default function ConfigPanel({
  config,
  onChange,
  models
}: {
  config: ApiConfig
  onChange: (value: Partial<ApiConfig>) => void
  models: string[]
}) {
  const hasModels = models && models.length > 0
  const selected = config.geminiModel
  const options = hasModels ? models : []
  return (
    <div className="panel p-4">
      <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Configuration</div>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <div className="text-xs font-semibold text-slate-500">RapidPipeline API Base URL</div>
          <input
            className="input"
            value={config.apiBaseUrl}
            onChange={(e) => onChange({ apiBaseUrl: e.target.value })}
            placeholder="https://api.rapidpipeline.com"
          />
        </div>
        <div className="space-y-2">
          <div className="text-xs font-semibold text-slate-500">Bearer Token</div>
          <input
            className="input"
            type="password"
            value={config.bearerToken}
            onChange={(e) => onChange({ bearerToken: e.target.value })}
            placeholder="••••••••••"
          />
        </div>
        <div className="space-y-2">
          <div className="text-xs font-semibold text-slate-500">Gemini Model</div>
          <select
            className="input"
            value={selected}
            onChange={(e) => onChange({ geminiModel: e.target.value })}
          >
            <option value="">{hasModels ? "Select model" : "No models available"}</option>
            {options.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <div className="text-xs font-semibold text-slate-500">Gemini API Key</div>
          <input
            className="input"
            type="password"
            value={config.geminiApiKey}
            onChange={(e) => onChange({ geminiApiKey: e.target.value })}
            placeholder="••••••••••"
          />
        </div>
      </div>
    </div>
  )
}
