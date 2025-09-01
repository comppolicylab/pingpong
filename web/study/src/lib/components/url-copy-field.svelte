<script lang="ts">
	import Button from '$lib/components/ui/button/button.svelte';
	import { Input } from '$lib/components/ui/input/index.js';
	import CopyIcon from '@lucide/svelte/icons/copy';
	import CheckIcon from '@lucide/svelte/icons/check';

	let { url, class: className }: { url: string; class?: string } = $props();

	let copied = $state(false);
	let hover = $state(false);
	let keep = $state(false);
	let timer: number | undefined;

	async function copyUrl() {
		try {
			await navigator.clipboard.writeText(url);
			copied = true;
			keep = true;
			if (timer) {
				clearTimeout(timer);
				timer = undefined;
			}
		} catch {
			// ignore
		}
	}

	function onEnter() {
		hover = true;
		if (timer) {
			clearTimeout(timer);
			timer = undefined;
		}
		if (copied) keep = true;
	}
	function onLeave() {
		hover = false;
		if (copied) {
			if (timer) clearTimeout(timer);
			timer = window.setTimeout(() => {
				keep = false;
				copied = false;
			}, 600);
		} else {
			keep = false;
		}
	}

	const showCopied = $derived(copied && (hover || keep));
</script>

<div class={`flex w-full items-center ${className ?? ''}`}>
	<Input
		value={url}
		readonly
		aria-label="URL"
		class="rounded-r-none border-r-0 font-mono text-xs sm:text-sm"
	/>
	<Button
		variant="default"
		aria-label={showCopied ? 'Copied' : 'Copy link'}
		onclick={copyUrl}
		onmouseenter={onEnter}
		onmouseleave={onLeave}
		class="relative h-9 rounded-l-none border border-l-0 border-input px-3 whitespace-nowrap"
	>
		<!-- Reserve width based on the default (not-copied) content -->
		<span aria-hidden="true" class="invisible inline-flex items-center gap-1.5">
			<CopyIcon class="size-3.5" />
			<span>Copy</span>
		</span>
		<!-- Actual visible content overlay, centered -->
		<span class="absolute inset-0 grid place-items-center">
			{#if showCopied}
				<CheckIcon class="size-4" />
			{:else}
				<span class="inline-flex items-center gap-1.5">
					<CopyIcon class="size-3.5" />
					<span>Copy</span>
				</span>
			{/if}
		</span>
	</Button>
</div>
