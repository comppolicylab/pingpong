import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), '');
	const backendPort = env.BACKEND_PORT || '8000';
	const backendHost = `localhost:${backendPort}`;

	return {
		plugins: [sveltekit(), tailwindcss()],
		test: {
			include: ['src/**/*.{test,spec}.{js,ts}']
		},
		server: {
			proxy: {
				'^/api/v1/class/.*/thread/.*/audio': {
					target: `ws://${backendHost}`,
					ws: true
				},
				'/api': {
					target: `http://${backendHost}`,
					secure: false
				}
			}
		}
	};
});
