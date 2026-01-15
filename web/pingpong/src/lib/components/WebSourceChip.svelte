<script lang="ts">
	import type { WebSearchSource } from '$lib/api';
	import { Tooltip } from 'flowbite-svelte';
	import { parse } from 'tldts';

	interface Props {
		source: WebSearchSource;
		type?: 'chip' | 'list';
		forceEagerLoad?: boolean;
	}

	let { source, type = 'chip', forceEagerLoad = false }: Props = $props();

	const domainFromUrl = (url?: string | null) => {
		if (!url) return '';
		const parsed = parse(url);
		if (parsed.domain) {
			return parsed.domain;
		}
		try {
			const parsedUrl = new URL(url);
			return parsedUrl.hostname;
		} catch (err) {
			console.error('Invalid URL provided to WebSourceChip', err);
			return url;
		}
	};

	let domain = $derived(domainFromUrl(source?.url));
	let faviconUrl = $derived(
		source?.url
			? `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(domain)}&sz=64`
			: undefined
	);

	let label = $derived(source?.title || domain || source?.url || 'Source');

	let showFavicon = $derived(Boolean(faviconUrl));

	const handleFaviconLoad = (event: Event & { currentTarget: EventTarget & Element }) => {
		if (!(event.currentTarget instanceof HTMLImageElement)) return;
		const { naturalWidth, naturalHeight } = event.currentTarget;
		if (naturalWidth <= 16 && naturalHeight <= 16) {
			showFavicon = false;
		}
	};

	const stripUtmParams = (rawUrl?: string | null) => {
		if (!rawUrl) return null;
		try {
			const url = new URL(rawUrl);
			url.searchParams.forEach((_, key) => {
				if (key.toLowerCase().startsWith('utm_')) {
					url.searchParams.delete(key);
				}
			});
			return url.toString();
		} catch (err) {
			console.error('Invalid URL provided to WebSourceChip', err);
			return rawUrl;
		}
	};
	const url = $derived(stripUtmParams(source?.url));
	const buttonClass = $derived(
		'inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 text-xs font-normal text-gray-700 hover:bg-gray-100' +
			(type === 'list' ? ' py-1 pl-2 pr-3 shadow-xs' : ' py-0.5 px-2')
	);
</script>

<button
	type="button"
	class={buttonClass}
	onclick={() => {
		if (url) {
			window.open(url, '_blank', 'noopener,noreferrer');
		}
	}}
>
	{#if faviconUrl && showFavicon && type === 'list'}
		<img
			alt="Favicon"
			src={faviconUrl}
			class="w-4 rounded-full"
			loading={forceEagerLoad ? 'eager' : 'lazy'}
			onload={handleFaviconLoad}
			onerror={() => (showFavicon = false)}
		/>
	{/if}
	<span>{domain}<span class="block"></span></span>
</button>
<Tooltip
	placement="top-start"
	arrow={false}
	class="flex flex-col gap-1 text-left text-sm font-normal"
>
	<div class="max-w-xs break-words">{label}</div>
	{#if url}
		<div class="flex max-w-xs flex-row items-center gap-2">
			{#if faviconUrl && showFavicon}
				<img
					alt="Favicon"
					src={faviconUrl}
					class="h-4 w-4 rounded-xs bg-white"
					loading={forceEagerLoad ? 'eager' : 'lazy'}
					onload={handleFaviconLoad}
					onerror={() => (showFavicon = false)}
				/>
			{/if}
			<div class="min-w-0 truncate text-xs font-light text-gray-300">{url}</div>
		</div>
	{/if}
</Tooltip>
