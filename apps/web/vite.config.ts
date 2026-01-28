import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import path from "node:path"
import { fileURLToPath } from "node:url"
import http from "node:http"
import https from "node:https"

function isAllowed(method: string, targetPath: string): boolean {
  if (method === "GET") {
    return targetPath === "/status" || targetPath === "/tools" || targetPath === "/files" || targetPath === "/config" || targetPath === "/gemini/models"
  }
  if (method === "DELETE") {
    return targetPath.startsWith("/files/")
  }
  if (method === "POST") {
    return targetPath === "/upload" || targetPath === "/config"
  }
  return false
}

function devProxyPlugin() {
  return {
    name: "rapidmcp-dev-proxy",
    configureServer(server) {
      server.middlewares.use("/api/proxy", (req, res) => {
        const method = (req.method || "GET").toUpperCase()
        const url = new URL(req.url || "", "http://localhost")
        const targetPath = url.searchParams.get("path") || ""
        if (!isAllowed(method, targetPath)) {
          res.statusCode = 400
          res.setHeader("content-type", "application/json")
          res.end(JSON.stringify({ error: "not_allowed" }))
          return
        }

        const headerHost = req.headers["x-host-url"]
        const queryHost = url.searchParams.get("host")
        const hostValue = (Array.isArray(headerHost) ? headerHost[0] : headerHost) || queryHost || "http://localhost:8080"
        const hostUrl = hostValue.replace(/\/$/, "")
        const target = new URL(hostUrl + targetPath)
        const client = target.protocol === "https:" ? https : http

        const { host, origin, referer, ...forwardHeaders } = req.headers
        delete forwardHeaders["x-host-url"]

        const proxyReq = client.request(
          {
            protocol: target.protocol,
            hostname: target.hostname,
            port: target.port,
            method,
            path: target.pathname + target.search,
            headers: {
              ...forwardHeaders,
              host: target.host
            }
          },
          (proxyRes) => {
            res.statusCode = proxyRes.statusCode || 500
            for (const [key, value] of Object.entries(proxyRes.headers)) {
              if (value === undefined) continue
              res.setHeader(key, value as string)
            }
            proxyRes.pipe(res)
          }
        )

        proxyReq.on("error", () => {
          res.statusCode = 502
          res.setHeader("content-type", "application/json")
          res.end(JSON.stringify({ error: "proxy_failed" }))
        })

        if (method === "GET" || method === "DELETE") {
          proxyReq.end()
          return
        }

        req.pipe(proxyReq)
      })
    }
  }
}

export default defineConfig({
  plugins: [react(), devProxyPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src")
    }
  },
  server: {
    port: 3000
  }
})
