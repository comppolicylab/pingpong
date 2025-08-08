<script lang="ts">
	import CopyIcon from '@lucide/svelte/icons/copy';
	import CheckIcon from '@lucide/svelte/icons/check';
	import Button from '../ui/button/button.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	let { url }: { url: string } = $props();
	let copiedUrl = $state(false);
	let isHovering = $state(false);
	let keepAfterHover = $state(false);
	let hoverHideTimer: number | undefined = undefined;

	async function copyUrl(e?: MouseEvent) {
		e?.stopPropagation();
		try {
			await navigator.clipboard.writeText(url);
			copiedUrl = true;
			keepAfterHover = true;
			if (hoverHideTimer) {
				clearTimeout(hoverHideTimer);
				hoverHideTimer = undefined;
			}
		} catch {
			// no-op
		}
	}

	function onMouseEnter() {
		isHovering = true;
		if (hoverHideTimer) {
			clearTimeout(hoverHideTimer);
			hoverHideTimer = undefined;
		}
		if (copiedUrl) keepAfterHover = true;
	}

	function onMouseLeave() {
		isHovering = false;
		if (copiedUrl) {
			if (hoverHideTimer) clearTimeout(hoverHideTimer);
			hoverHideTimer = window.setTimeout(() => {
				keepAfterHover = false;
				copiedUrl = false;
			}, 600);
		} else {
			keepAfterHover = false;
		}
	}

	const showCopied = $derived(copiedUrl && (isHovering || keepAfterHover));
</script>

<Tooltip.Provider delayDuration={150}>
	<Tooltip.Root>
		<Tooltip.Trigger>
			<Button
				variant="outline"
				size="sm"
				class="whitespace-nowrap"
				aria-label={copiedUrl ? 'Copied' : 'Copy Link'}
				onclick={copyUrl}
				onmouseenter={onMouseEnter}
				onmouseleave={onMouseLeave}
			>
				{#if showCopied}
					<CheckIcon />
					Copied!
				{:else}
					<CopyIcon />
					Copy Link
				{/if}
			</Button>
		</Tooltip.Trigger>
		<Tooltip.Content side="top" sideOffset={2}>
			<span class="font-mono text-[11px]">{url}</span>
		</Tooltip.Content>
	</Tooltip.Root>
</Tooltip.Provider>
