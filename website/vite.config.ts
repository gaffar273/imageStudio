import { fileURLToPath } from 'node:url'
import { defineConfig, type Connect } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const productPages = ['product/image-studio', 'product/glideYT']
const serveProductPage: Connect.NextHandleFunction = (req, _res, next) => {
  const url = new URL(req.url ?? '/', 'http://localhost')
  const path = url.pathname.replace(/^\/|\/$/g, '')
  if (productPages.includes(path)) req.url = '/' + path + '/index.html' + url.search
  next()
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: 'product-pages',
      configureServer(server) { server.middlewares.use(serveProductPage) },
      configurePreviewServer(server) { server.middlewares.use(serveProductPage) },
    },
  ],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    rolldownOptions: { input: ['index.html', ...productPages.map(path => path + '/index.html')] },
  },
})
