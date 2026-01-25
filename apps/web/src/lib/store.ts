const HOST_KEY = "rapidmcp_host_url"
const SESSION_KEY = "rapidmcp_session_id"

export function loadHostUrl(): string {
  if (typeof window === "undefined") return ""
  return localStorage.getItem(HOST_KEY) || ""
}

export function saveHostUrl(value: string) {
  if (typeof window === "undefined") return
  localStorage.setItem(HOST_KEY, value)
}

export function getSessionId(): string {
  if (typeof window === "undefined") return ""
  let id = localStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, id)
  }
  return id
}
