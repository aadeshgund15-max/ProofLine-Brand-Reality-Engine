import { defineConfig } from 'vite'

export default defineConfig({
  base: process.env.GITHUB_ACTIONS ? '/ProofLine-Brand-Reality-Engine/' : '/',
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // Uvicorn binds to IPv4 loopback by default. On Windows, localhost may
      // resolve to ::1 first, so targeting localhost can yield proxy 502s.
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
