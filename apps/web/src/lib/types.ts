export type Status = {
  gemini: "ok" | "down"
  mcpApi: "ok" | "down"
  fsMcp: "ok" | "down"
  model: string
  toolsCount: number
}

export type Tool = {
  name: string
  description: string
  inputSchema: any
  source: "api" | "fs" | "host"
}

export type FileItem = {
  id: string
  name: string
  size: number
  created: string
  uri: string
}

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
}

export type ToolEvent = {
  callId: string
  name: string
  status: "running" | "done" | "error"
  progress?: number
  message?: string
  result?: any
  error?: string
}

export type ApiConfig = {
  apiBaseUrl: string
  bearerToken: string
  geminiApiKey: string
  geminiModel: string
}
