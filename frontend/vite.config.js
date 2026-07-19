import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import http from 'http'

const keepAliveAgent = new http.Agent({
  keepAlive: true,
  keepAliveMsecs: 30000
})

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: false,
        agent: keepAliveAgent
      }
    }
  },
  preview: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: false,
        agent: keepAliveAgent
      }
    }
  }
})