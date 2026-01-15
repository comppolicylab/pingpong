<script lang="ts">
	import { DropdownItem } from 'flowbite-svelte';
	interface Props {
		colorClasses?: string;
		hoverable?: boolean;
		hoverColorClasses?: string;
		link?: string;
		children?: import('svelte').Snippet;
	}

	let {
		colorClasses = 'from-gray-800 to-gray-600',
		hoverable = false,
		hoverColorClasses = 'hover:from-gray-900 hover:to-gray-700',
		link = '',
		children
	}: Props = $props();
</script>

{#if link}
	<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
	<a href={link} data-sveltekit-reload rel="noopener noreferrer" target="_blank"
		><DropdownItem
			class="bg-gradient-to-r {colorClasses} text-white {hoverable
				? hoverColorClasses
				: ''} rounded-b-lg border-t">{@render children?.()}</DropdownItem
		></a
	>
{:else}<DropdownItem
		class="bg-gradient-to-r {colorClasses} text-white {hoverable
			? hoverColorClasses
			: ''} rounded-b-lg border-t">{@render children?.()}</DropdownItem
	>{/if}
