import { useState } from "react"
import { ChatMessage } from "@/lib/types"

export default function ChatPanel({
  messages,
  draftAssistant,
  onSend,
  isProcessing
}: {
  messages: ChatMessage[]
  draftAssistant: string
  isProcessing: boolean
  onSend: (text: string) => void
}) {
  const [input, setInput] = useState("")

  const handleSubmit = () => {
    if (!input.trim() || isProcessing) return
    onSend(input)
    setInput("")
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="rounded-2xl border border-black/10 bg-white/70 shadow-[0_20px_60px_var(--shadow)] p-4 backdrop-blur flex flex-col">
      <div className="text-sm uppercase tracking-[0.2em] text-black/50">Chat</div>
      <div className="mt-4 space-y-4 flex-1 overflow-auto max-h-[420px] pr-2">
        {messages.map((m) => (
          <div key={m.id} className={`rounded-2xl px-4 py-3 ${m.role === "user" ? "bg-amber-100 border border-amber-200" : "bg-white border border-black/10"}`}>
            <div className="text-xs uppercase tracking-[0.2em] text-black/40">{m.role}</div>
            <div className="mt-2 text-sm whitespace-pre-wrap">{m.content}</div>
          </div>
        ))}
        {draftAssistant && (
          <div className="rounded-2xl px-4 py-3 bg-white border border-dashed border-black/20">
            <div className="text-xs uppercase tracking-[0.2em] text-black/40">assistant</div>
            <div className="mt-2 text-sm whitespace-pre-wrap">{draftAssistant}</div>
          </div>
        )}
      </div>
      <div className="mt-4 flex flex-col gap-2">
        <textarea
          className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm bg-white min-h-[90px] disabled:opacity-60"
          placeholder={isProcessing ? "Processing request..." : "Ask something or call a tool"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isProcessing}
        />
        <button
          className="rounded-xl bg-[var(--accent)] text-white px-4 py-2 text-sm disabled:opacity-60 disabled:cursor-not-allowed"
          onClick={handleSubmit}
          disabled={isProcessing}
        >
          {isProcessing ? "Processing..." : "Send"}
        </button>
      </div>
    </div>
  )
}
