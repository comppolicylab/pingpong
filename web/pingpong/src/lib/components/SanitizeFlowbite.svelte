<script lang="ts">
	import DOMPurify from '$lib/purify';
	import { Heading, Li, List } from 'flowbite-svelte'; // eslint-disable-line @typescript-eslint/no-unused-vars

	
	interface Props {
		/**
		 * Content to render.
		 */
		html: string | Promise<string>;
	}

	let { html }: Props = $props();

	let sanitized = $state('');

	const flowbiteSvelteTags = ['Heading', 'List', 'Li'];

	DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
		if (data.attrName === 'customsize' && node.nodeName !== 'HEADING') {
			data.keepAttr = false; // Remove the attribute if not on <Heading>
		}
	});

	// Sanitize the document.
	$effect(() => {
		sanitizeInput(html);
	});

	function sanitizeContent(content: string) {
		return DOMPurify.sanitize(content, {
			ADD_TAGS: flowbiteSvelteTags,
			ADD_ATTR: ['customsize', 'tag']
		})
			.replace(/<heading\b/gi, '<Heading')
			.replace(/<\/heading>/gi, '</Heading>')
			.replace(/<list\b/gi, '<List')
			.replace(/<\/list>/gi, '</List>')
			.replace(/<li\b/gi, '<Li')
			.replace(/<\/li>/gi, '</Li>');
	}

	function sanitizeInput(value: string | Promise<string>) {
		if (typeof value === 'string') {
			sanitized = sanitizeContent(value);
			return;
		}

		sanitized = '';
		const pending = value;
		pending.then((content) => {
			// Guard against stale promise resolutions.
			if (pending === html) {
				sanitized = sanitizeContent(content);
			}
		});
	}
</script>

<div>
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html sanitized}
</div>
