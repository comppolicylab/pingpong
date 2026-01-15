<script lang="ts">
	import DOMPurify from '$lib/purify';

	interface Props {
		/**
		 * Content to render.
		 */
		html: string | Promise<string>;
	}

	let { html }: Props = $props();

	let sanitized = $state('');

	// Sanitize the document.
	$effect(() => {
		sanitizeInput(html);
	});

	function sanitizeInput(value: string | Promise<string>) {
		if (typeof value === 'string') {
			sanitized = DOMPurify.sanitize(value);
			return;
		}

		sanitized = '';
		const pending = value;
		pending.then((content) => {
			// Only update if the same promise is still current to avoid stale writes.
			if (pending === html) {
				sanitized = DOMPurify.sanitize(content);
			}
		});
	}
</script>

<div>
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html sanitized.replace(/<a\b([^>]*)>(.*?)<\/a>/gi, (match, attrs, text) => {
		return /href\s*=\s*(['"])[^'"]+\1/.test(attrs) ? match : `<span${attrs}>${text}</span>`;
	})}
</div>
