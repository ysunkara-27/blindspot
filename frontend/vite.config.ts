/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { normalizeBase } from './src/api/base.ts';

// VITE_BASE_PATH (default "/") sets the public path: `npm run build:site` builds for https://ysunkara.com/blindspot/.
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), 'VITE_'), ...process.env };
  const base = normalizeBase(env.VITE_BASE_PATH);
  // VITE_API_PROXY: where the dev server forwards /api (default the local API on :8000).
  const target = env.VITE_API_PROXY || 'http://127.0.0.1:8000';
  // Dev server: the API is always mounted at /api on :8000; under a sub-path, strip the prefix on the way through.
  const proxy: Record<string, object> = { '/api': { target, changeOrigin: true } };
  if (base !== '/') proxy[`${base}api`] = { target, changeOrigin: true, rewrite: (p: string) => p.slice(base.length - 1) };
  return {
    base,
    plugins: [react()],
    server: { port: 5173, proxy },
    test: { environment: 'node', include: ['src/**/*.test.ts', 'src/**/*.test.tsx'] },
  };
});
