import { Status, Tool, FileItem, ApiConfig } from "@/lib/types"

async function apiFetch(hostUrl: string, path: string, options: RequestInit) {
  const url = import.meta.env.DEV
    ? `/api/proxy?path=${encodeURIComponent(path)}`
    : `${hostUrl.replace(/\/$/, "")}${path}`
  const headers = new Headers(options.headers || {})
  if (import.meta.env.DEV) {
    headers.set("x-host-url", hostUrl)
  }
  const resp = await fetch(url, { ...options, headers })
  if (!resp.ok) return null
  return await resp.json()
}

export async function getStatus(hostUrl: string): Promise<Status | null> {
  return await apiFetch(hostUrl, "/status", { method: "GET" })
}

export async function getTools(hostUrl: string): Promise<Tool[] | null> {
  const data = await apiFetch(hostUrl, "/tools", { method: "GET" })
  return data ? data.tools : null
}

export async function getFiles(hostUrl: string): Promise<FileItem[] | null> {
  const data = await apiFetch(hostUrl, "/files", { method: "GET" })
  return data ? data.files : null
}

export async function deleteFile(hostUrl: string, id: string) {
  return await apiFetch(hostUrl, `/files/${id}`, { method: "DELETE" })
}

export async function uploadFile(hostUrl: string, file: File) {
  const formData = new FormData()
  formData.append("file", file)
  const url = import.meta.env.DEV
    ? `/api/proxy?path=${encodeURIComponent("/upload")}`
    : `${hostUrl.replace(/\/$/, "")}/upload`
  const headers = new Headers()
  if (import.meta.env.DEV) {
    headers.set("x-host-url", hostUrl)
  }
  const resp = await fetch(url, { method: "POST", body: formData, headers })
  if (!resp.ok) return null
  return await resp.json()
}

export async function getConfig(hostUrl: string): Promise<ApiConfig | null> {
  return await apiFetch(hostUrl, "/config", { method: "GET" })
}

export async function setConfig(hostUrl: string, config: ApiConfig): Promise<ApiConfig | null> {
  return await apiFetch(hostUrl, "/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config)
  })
}
