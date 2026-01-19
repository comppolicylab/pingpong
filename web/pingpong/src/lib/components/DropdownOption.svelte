<script lang="ts">
	import { DropdownItem, Tooltip } from 'flowbite-svelte';
	import { BrainOutline } from 'flowbite-svelte-icons';
	export let value: string;
	export let selectedValue: string;
	export let update: (value: string) => void;
	export let name: string;
	export let subtitle: string;
	export let smallNameText: boolean = false;
	export let addBrainIcon: boolean = false;
</script>

<DropdownItem
	onclick={() => update(value)}
	defaultClass="flex flex-col gap-x-1 gap-y-1 font-medium py-2 px-4 text-sm scroll-mt-9 {value ==
	selectedValue
		? 'text-blue-900 bg-blue-light-40 hover:bg-blue-light-40 hover:text-blue-900'
		: 'hover:bg-gray-100 dark:hover:bg-gray-600'}"
>
	<div class="flex w-full flex-row flex-wrap items-center justify-between gap-x-3">
		<div class="flex flex-row items-center gap-2">
			<span class={smallNameText ? 'text-md' : 'text-lg'}>{name}</span>
			{#if addBrainIcon}<BrainOutline size={smallNameText ? 'sm' : 'md'} /><Tooltip
					class="z-[100] font-light {smallNameText ? 'text-xs' : 'text-sm'}"
					>Reasoning model</Tooltip
				>
			{/if}
		</div>
		<div class="flex flex-row flex-wrap items-center gap-x-1 gap-y-0.5">
			<slot />
		</div>
	</div>
	<span class="font-normal">{subtitle}</span>
</DropdownItem>
