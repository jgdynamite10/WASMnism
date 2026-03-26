import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    proxy: {
      '/gateway': {
        target: 'https://wasm-prompt-firewall-imjy4pe0.fermyon.app',
        changeOrigin: true,
        secure: true,
      },
      '/api': {
        target: 'https://wasm-prompt-firewall-imjy4pe0.fermyon.app',
        changeOrigin: true,
        secure: true,
      }
    }
  }
})
