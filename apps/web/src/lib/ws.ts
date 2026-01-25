export type WsHandlers = {
  onOpen?: () => void
  onClose?: () => void
  onError?: () => void
  onMessage?: (data: any) => void
}

export type WsClient = {
  send: (data: any) => void
  close: () => void
}

function toWsUrl(hostUrl: string): string {
  if (hostUrl.startsWith("https://")) return hostUrl.replace("https://", "wss://") + "/ws"
  if (hostUrl.startsWith("http://")) return hostUrl.replace("http://", "ws://") + "/ws"
  return "ws://localhost:8080/ws"
}

export function connectWs(hostUrl: string, handlers: WsHandlers): WsClient {
  const ws = new WebSocket(toWsUrl(hostUrl))
  ws.onopen = () => handlers.onOpen?.()
  ws.onclose = () => handlers.onClose?.()
  ws.onerror = () => handlers.onError?.()
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      handlers.onMessage?.(data)
    } catch {
      handlers.onMessage?.({ type: "raw", content: event.data })
    }
  }
  return {
    send: (data: any) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(data)),
    close: () => ws.close()
  }
}
