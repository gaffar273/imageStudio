import { fileURLToPath } from 'node:url'
import { defineConfig, type Connect } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const pages = ['product/image-studio', 'product/glideYT', 'product/rillboard', 'downloads', 'support']
const servePage: Connect.NextHandleFunction = (req, res, next) => {
  const url = new URL(req.url ?? '/', 'http://localhost')
  const path = url.pathname.replace(/^\/|\/$/g, '')
  // Vite treats .gz files as precompressed responses. This archive is itself the download.
  if (/^downloads\/rillboard\/\d+\.\d+\.\d+\/rillboard-linux\.tar\.gz$/.test(path)) {
    res.setHeader('Content-Type', 'application/gzip')
    res.setHeader('Content-Encoding', 'identity')
  }
  if (pages.includes(path)) req.url = '/' + path + '/index.html' + url.search
  next()
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'site-pages',
      configureServer(server) { server.middlewares.use(servePage) },
      configurePreviewServer(server) { server.middlewares.use(servePage) },
    },
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    rolldownOptions: { input: ['index.html', ...pages.map(path => path + '/index.html')] },
  },
})
