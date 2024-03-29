import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

const ClosePlugin = () => {
  return {
    name: 'ClosePlugin',
    buildEnd: (error: Error | string | null | undefined) => {
      if (error) {
        console.error("Error during build:")
        console.error(error);
        process.exit(1);
      } else {
        console.log("Build finished!");
        process.exit(0);
      }
    },
    closeBundle() {
      console.log('Closing bundle');
      process.exit(0);
    }
  };

}


export default defineConfig({
  plugins: [
    sveltekit(),
    ClosePlugin(),
  ],
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}']
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        secure: false
      }
    }
  }
});
