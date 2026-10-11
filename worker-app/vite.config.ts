import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// In development the app calls `/api/...`; Vite forwards those requests to the
// FastAPI backend so the browser never needs CORS or a hard-coded backend URL.
// Deployed builds use VITE_API_BASE_URL instead (see src/config.ts).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const proxyTarget = env.VITE_DEV_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
