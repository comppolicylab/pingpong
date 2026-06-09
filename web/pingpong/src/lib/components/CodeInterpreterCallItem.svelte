<script lang="ts">
	import { slide } from 'svelte/transition';
	import {
		ChevronDownOutline,
		CodeOutline,
		ImageSolid,
		TerminalOutline
	} from 'flowbite-svelte-icons';

	export let label: string;
	export let icon: 'code' | 'image' | 'logs' = 'code';
	export let forceOpen = false;

	let open = false;
	let previousOpen: boolean | null = null;
	$: {
		if (forceOpen) {
			if (previousOpen === null) {
				previousOpen = open;
			}
			open = true;
		} else if (previousOpen !== null) {
			open = previousOpen;
			previousOpen = null;
		}
	}

	const toggle = () => (open = !open);
</script>

<div class="my-2">
	<button type="button" class="flex flex-row items-center gap-1" onclick={toggle}>
		<span class="inline-flex text-gray-600">
			{#if icon === 'logs'}
				<TerminalOutline class="h-4 w-4" />
			{:else if icon === 'image'}
				<ImageSolid class="h-4 w-4" />
			{:else}
				<CodeOutline class="h-4 w-4" />
			{/if}
		</span>
		<span class="text-sm font-medium text-gray-600">{label}{open ? '...' : ''}</span>
		{#if open}
			<ChevronDownOutline class="rotate-180 transform text-gray-600" />
		{:else}
			<ChevronDownOutline class="text-gray-600" />
		{/if}
	</button>

	{#if open}
		<div
			class="mt-2 ml-2 border-l border-gray-200 pl-4 text-sm font-light text-gray-600"
			transition:slide={{ duration: 250 }}
		>
			<div class="rounded border border-gray-200 bg-gray-50 px-4 py-3">
				<slot />
			</div>
		</div>
	{/if}
</div>
