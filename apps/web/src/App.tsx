import { useEffect, useRef, useState } from "react"
import StatusBar from "@/components/StatusBar"
import Sidebar from "@/components/Sidebar"
import ChatPanel from "@/components/ChatPanel"
import ToolActivity from "@/components/ToolActivity"
import FilesPanel from "@/components/FilesPanel"
import { Status, Tool, FileItem, ChatMessage, ToolEvent, ApiConfig } from "@/lib/types"
import { connectWs, WsClient } from "@/lib/ws"
import { getFiles, getStatus, getTools, uploadFile, deleteFile, getConfig, setConfig } from "@/lib/http"
import { getSessionId, loadHostUrl, saveHostUrl, loadApiConfig, saveApiConfig } from "@/lib/store"

const emptyStatus: Status = {
  gemini: "down",
  mcpApi: "down",
  fsMcp: "down",
  model: "gemini",
  toolsCount: 0
}

export default function App() {
  const [hostUrl, setHostUrl] = useState("http://localhost:8080")
  const [status, setStatus] = useState<Status>(emptyStatus)
  const [tools, setTools] = useState<Tool[]>([])
  const [files, setFiles] = useState<FileItem[]>([])
  const [selectedFiles, setSelectedFiles] = useState<Record<string, boolean>>({})
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draftAssistant, setDraftAssistant] = useState("")
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [sessionId, setSessionId] = useState("")
  const [wsNonce, setWsNonce] = useState(0)
  const [apiConfig, setApiConfigState] = useState<ApiConfig>({ apiBaseUrl: "", bearerToken: "" })
  const [isSavingConfig, setIsSavingConfig] = useState(false)
  const wsRef = useRef<WsClient | null>(null)

  useEffect(() => {
    const url = loadHostUrl() || "http://localhost:8080"
    setHostUrl(url)
    setSessionId(getSessionId())
    setApiConfigState(loadApiConfig())
  }, [])

  useEffect(() => {
    if (!sessionId) return
    const client = connectWs(hostUrl, {
      onOpen: () => {
        setConnected(true)
        client.send({ type: "hello", sessionId })
      },
      onClose: () => {
        setConnected(false)
        setIsProcessing(false)
      },
      onMessage: (data) => handleWsMessage(data)
    })
    wsRef.current = client
    return () => client.close()
  }, [hostUrl, sessionId, wsNonce])

  useEffect(() => {
    if (!hostUrl) return
    saveHostUrl(hostUrl)
  }, [hostUrl])

  useEffect(() => {
    if (!hostUrl) return
    let alive = true
    const load = async () => {
      const cfg = await getConfig(hostUrl)
      if (!alive || !cfg) return
      setApiConfigState(cfg)
      saveApiConfig(cfg.apiBaseUrl, cfg.bearerToken)
    }
    load()
    return () => {
      alive = false
    }
  }, [hostUrl])

  useEffect(() => {
    let alive = true
    const refresh = async () => {
      const nextStatus = await getStatus(hostUrl)
      const nextTools = await getTools(hostUrl)
      const nextFiles = await getFiles(hostUrl)
      if (!alive) return
      if (nextStatus) setStatus(nextStatus)
      if (nextTools) setTools(nextTools)
      if (nextFiles) syncFiles(nextFiles)
    }
    refresh()
    const id = setInterval(refresh, 5000)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [hostUrl])

  const syncFiles = (nextFiles: FileItem[]) => {
    setFiles(nextFiles)
    const nextSelected: Record<string, boolean> = {}
    for (const f of nextFiles) {
      if (selectedFiles[f.id]) nextSelected[f.id] = true
    }
    setSelectedFiles(nextSelected)
  }

  const refreshFiles = async () => {
    const nextFiles = await getFiles(hostUrl)
    if (nextFiles) syncFiles(nextFiles)
  }

  const handleWsMessage = (data: any) => {
    if (!data || typeof data !== "object") return
    if (data.type === "status") {
      setStatus({
        gemini: data.gemini,
        mcpApi: data.mcpApi,
        fsMcp: data.fsMcp,
        model: data.model,
        toolsCount: data.toolsCount
      })
      return
    }
    if (data.type === "assistant_delta") {
      setDraftAssistant((prev) => prev + (data.content || ""))
      return
    }
    if (data.type === "assistant_message") {
      const content = data.content || ""
      setDraftAssistant("")
      setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", content }])
      setIsProcessing(false)
      return
    }
    if (data.type === "tool_start") {
      setToolEvents((prev) => [...prev, { callId: data.callId, name: data.name, status: "running", progress: 0 }])
      return
    }
    if (data.type === "tool_progress") {
      setToolEvents((prev) =>
        prev.map((e) => e.callId === data.callId ? { ...e, progress: data.progress, message: data.message } : e)
      )
      return
    }
    if (data.type === "tool_end") {
      setToolEvents((prev) =>
        prev.map((e) => e.callId === data.callId ? { ...e, status: "done", result: data.result, progress: 1 } : e)
      )
      refreshFiles()
      return
    }
    if (data.type === "tool_error") {
      setToolEvents((prev) => prev.map((e) => e.callId === data.callId ? { ...e, status: "error", error: data.error } : e))
      refreshFiles()
    }
  }

  const handleSend = (text: string) => {
    if (!text.trim() || isProcessing) return
    const fileUris = files.filter((f) => selectedFiles[f.id]).map((f) => f.uri)
    const msg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text }
    setMessages((prev) => [...prev, msg])
    setIsProcessing(true)
    wsRef.current?.send({ type: "user_message", sessionId, content: text, fileUris })
  }

  const handleReconnect = () => {
    setWsNonce((v) => v + 1)
  }

  const handleConfigChange = (partial: Partial<ApiConfig>) => {
    setApiConfigState((prev) => ({ ...prev, ...partial }))
  }

  const handleConfigSave = async () => {
    setIsSavingConfig(true)
    const saved = await setConfig(hostUrl, apiConfig)
    if (saved) {
      setApiConfigState(saved)
      saveApiConfig(saved.apiBaseUrl, saved.bearerToken)
    }
    setIsSavingConfig(false)
  }

  const handleUpload = async (file: File) => {
    await uploadFile(hostUrl, file)
    const nextFiles = await getFiles(hostUrl)
    if (nextFiles) setFiles(nextFiles)
  }

  const handleDelete = async (id: string) => {
    await deleteFile(hostUrl, id)
    const nextFiles = await getFiles(hostUrl)
    if (nextFiles) setFiles(nextFiles)
  }

  const toggleFile = (id: string) => {
    setSelectedFiles((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  return (
    <div className="h-screen flex flex-col">
      <StatusBar
        status={status}
        hostUrl={hostUrl}
        connected={connected}
        onHostUrlChange={setHostUrl}
        onReconnect={handleReconnect}
        apiConfig={apiConfig}
        onApiConfigChange={handleConfigChange}
        onSaveApiConfig={handleConfigSave}
        isSavingConfig={isSavingConfig}
      />
      <div className="flex-1 px-6 py-6 min-h-0 overflow-hidden">
        <div className="max-w-6xl mx-auto h-full overflow-hidden">
          <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6 h-full items-stretch min-h-0">
            <Sidebar tools={tools} />
            <div className="grid grid-rows-[minmax(0,2fr)_minmax(0,1fr)] gap-6 h-full min-h-0">
              <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-6 min-h-0">
                <ChatPanel messages={messages} draftAssistant={draftAssistant} onSend={handleSend} isProcessing={isProcessing} />
                <ToolActivity events={toolEvents} />
              </div>
              <FilesPanel
                files={files}
                selectedFiles={selectedFiles}
                onToggle={toggleFile}
                onUpload={handleUpload}
                onDelete={handleDelete}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
