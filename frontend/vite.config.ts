import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // import.meta.dirname (not the CJS __dirname global) — Vite's upcoming
      // "native" config loader doesn't support __dirname.
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8001',
    },
  },
})
