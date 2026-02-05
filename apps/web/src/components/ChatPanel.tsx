import { useEffect, useRef, useState } from "react"
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
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
  }, [messages, draftAssistant])

  useEffect(() => {
    if (isProcessing) return
    inputRef.current?.focus()
  }, [isProcessing])

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
    <div className="panel p-4 flex flex-col h-full min-h-0 min-w-0">
      <div className="text-xs uppercase tracking-[0.2em] text-slate-400">Chat</div>
      <div ref={scrollRef} className="mt-4 space-y-4 flex-1 overflow-y-auto overflow-x-auto pr-2 min-h-0 min-w-0">
        {messages.map((m) => (
          <div key={m.id} className={`rounded-2xl px-4 py-3 max-w-full min-w-0 ${m.role === "user" ? "bg-slate-50 border border-slate-200" : "bg-white border border-slate-200"}`}>
            <div className="text-[11px] uppercase tracking-[0.2em] text-slate-400">{m.role}</div>
            <div className="mt-2 text-sm text-slate-700 whitespace-pre-wrap overflow-x-auto">{m.content}</div>
          </div>
        ))}
        {draftAssistant && (
          <div className="rounded-2xl px-4 py-3 bg-white border border-dashed border-slate-300 max-w-full min-w-0">
            <div className="text-[11px] uppercase tracking-[0.2em] text-slate-400">assistant</div>
            <div className="mt-2 text-sm text-slate-700 whitespace-pre-wrap overflow-x-auto">{draftAssistant}</div>
          </div>
        )}
      </div>
      <div className="mt-4 flex flex-col gap-2">
        <textarea
          className="input min-h-[90px] disabled:opacity-60"
          placeholder={isProcessing ? "Processing request..." : "Ask something or call a tool"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isProcessing}
          ref={inputRef}
        />
        <button
          className="btn-primary disabled:opacity-60 disabled:cursor-not-allowed"
          onClick={handleSubmit}
          disabled={isProcessing}
        >
          {isProcessing ? "Processing..." : "Send"}
        </button>
      </div>
    </div>
  )
}
