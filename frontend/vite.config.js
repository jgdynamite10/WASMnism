import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/gateway': {
        target: 'https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app',
        changeOrigin: true,
        secure: true,
      },
      '/api': {
        target: 'https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app',
        changeOrigin: true,
        secure: true,
      }
    }
  }
})
