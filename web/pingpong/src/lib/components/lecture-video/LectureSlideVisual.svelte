<script lang="ts" generics="T">
	import { untrack, type Snippet } from 'svelte';

	let {
		contentKey,
		contentData,
		children
	}: {
		contentKey: string;
		contentData: T;
		children: Snippet<[T, () => void, () => void, boolean]>;
	} = $props();

	type Layer = { id: number; key: string; data: T };
	let layers: Layer[] = $state.raw([]);
	let displayedId = $state<number | null>(null);
	let failed = $state(false);
	let retry = $state(0);
	let nextId = 0;
	let lastRetry = 0;

	$effect(() => {
		const key = contentKey;
		const data = contentData;
		const attempt = retry;
		untrack(() => {
			const pending =
				attempt === lastRetry
					? layers
							.slice()
							.reverse()
							.find((layer) => layer.key === key)
					: undefined;
			lastRetry = attempt;
			if (pending) {
				if (pending.id === displayedId && layers.length > 1) failed = false;
				layers = layers
					.filter((layer) => layer.id === displayedId || layer.id === pending.id)
					.map((layer) => (layer === pending ? { ...layer, data } : layer));
				return;
			}
			failed = false;
			// Keep the actual outgoing DOM mounted, including its decoded image/frame.
			layers = [...layers.filter((layer) => layer.id === displayedId), { id: ++nextId, key, data }];
		});
	});

	function markReady(id: number, key: string) {
		untrack(() => {
			if (key !== contentKey || id === displayedId || !layers.some((layer) => layer.id === id))
				return;
			displayedId = id;
			layers = layers.filter((layer) => layer.id === id);
			failed = false;
		});
	}

	function markFailed(id: number, key: string) {
		untrack(() => {
			if (key === contentKey && layers.some((layer) => layer.id === id)) failed = true;
		});
	}

	function retryLoad() {
		layers = layers.filter((layer) => layer.id === displayedId);
		failed = false;
		retry += 1;
	}
</script>

<div class="relative h-full w-full">
	{#each layers as layer (layer.id)}
		<div
			class="absolute inset-0 h-full w-full"
			class:invisible={layer.id !== displayedId}
			aria-hidden={layer.id !== displayedId}
		>
			{@render children(
				layer.data,
				() => markReady(layer.id, layer.key),
				() => markFailed(layer.id, layer.key),
				layer.key === contentKey && layer.id === layers[layers.length - 1]?.id
			)}
		</div>
	{/each}
	{#if failed}
		<div
			role="status"
			class="absolute inset-x-0 bottom-4 flex items-center justify-center gap-3 bg-black/80 p-3 text-sm text-white"
		>
			<span>Unable to load slide.</span>
			<button
				type="button"
				class="underline"
				onclick={(event) => {
					event.stopPropagation();
					retryLoad();
				}}>Retry</button
			>
		</div>
	{/if}
</div>
