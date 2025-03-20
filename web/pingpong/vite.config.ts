import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [sveltekit()],
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}']
  },
  server: {
    proxy: {
      '^/api/v1/class/.*/thread/.*/audio': {
        target: 'ws://localhost:8000',
        ws: true
      },
      '/api': {
        target: 'http://localhost:8000',
        secure: false
      }
    }
  }
});
