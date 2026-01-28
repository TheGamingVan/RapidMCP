const HOST_KEY = "rapidmcp_host_url"
const SESSION_KEY = "rapidmcp_session_id"
const API_BASE_KEY = "rapidmcp_api_base_url"
const API_TOKEN_KEY = "rapidmcp_api_bearer_token"
const GEMINI_KEY = "rapidmcp_gemini_api_key"
const GEMINI_MODEL = "rapidmcp_gemini_model"

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

export function loadApiConfig(): { apiBaseUrl: string; bearerToken: string; geminiApiKey: string; geminiModel: string } {
  if (typeof window === "undefined") return { apiBaseUrl: "", bearerToken: "", geminiApiKey: "", geminiModel: "" }
  return {
    apiBaseUrl: localStorage.getItem(API_BASE_KEY) || "",
    bearerToken: localStorage.getItem(API_TOKEN_KEY) || "",
    geminiApiKey: localStorage.getItem(GEMINI_KEY) || "",
    geminiModel: localStorage.getItem(GEMINI_MODEL) || ""
  }
}

export function saveApiConfig(apiBaseUrl: string, bearerToken: string, geminiApiKey: string, geminiModel: string) {
  if (typeof window === "undefined") return
  localStorage.setItem(API_BASE_KEY, apiBaseUrl)
  localStorage.setItem(API_TOKEN_KEY, bearerToken)
  localStorage.setItem(GEMINI_KEY, geminiApiKey)
  localStorage.setItem(GEMINI_MODEL, geminiModel)
}
