import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        configure(proxy) {
          proxy.on('proxyReq', (proxyRequest, request) => {
            const allowed = new Set(['http://127.0.0.1:5173', 'http://localhost:5173']);
            const origin = request.headers.origin;
            const token = process.env.TRANSCRIPT_API_TOKEN;
            proxyRequest.removeHeader('authorization');
            if (request.headers['x-transcript-client'] === 'browser' && (!origin || allowed.has(origin)) && token && token.length >= 32) {
              proxyRequest.setHeader('Authorization', `Bearer ${token}`);
            }
          });
        },
      },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
});
