<script lang="ts">
	import type { AssistantModelOptions } from '$lib/api';
	import { ImageOutline, StarSolid } from 'flowbite-svelte-icons';
	import DropdownBadge from './DropdownBadge.svelte';
	import DropdownOption from './DropdownOption.svelte';

	interface Props {
		modelOptions: AssistantModelOptions[];
		modelNodes: { [key: string]: HTMLElement };
		selectedModel: string;
		updateSelectedModel: (model: string) => void;
		allowVisionUpload: boolean;
		smallNameText?: boolean;
	}

	let {
		modelOptions,
		modelNodes = $bindable(),
		selectedModel,
		updateSelectedModel,
		allowVisionUpload,
		smallNameText = false
	}: Props = $props();
</script>

<div class="relative">
	{#each modelOptions as { value, name, description, supports_vision, supports_reasoning, is_new, highlight } (value)}
		<div bind:this={modelNodes[value]}>
			<DropdownOption
				{value}
				{name}
				subtitle={description}
				selectedValue={selectedModel}
				update={updateSelectedModel}
				{smallNameText}
				addBrainIcon={supports_reasoning}
			>
				{#if highlight}
					<DropdownBadge extraClasses="border-amber-400 from-amber-50 to-amber-100 text-amber-700"
						>{#snippet icon()}
							<span><StarSolid size="sm" /></span>
						{/snippet}{#snippet name()}
							<span>Recommended</span>
						{/snippet}
					</DropdownBadge>
				{/if}
				{#if is_new}
					<DropdownBadge extraClasses="border-green-400 from-green-100 to-green-200 text-green-800"
						>{#snippet name()}
							<span>New</span>
						{/snippet}</DropdownBadge
					>
				{/if}
				{#if supports_vision && allowVisionUpload}
					<DropdownBadge extraClasses="border-gray-400 from-gray-100 to-gray-200 text-gray-800"
						>{#snippet icon()}
							<span><ImageOutline size="sm" /></span>
						{/snippet}{#snippet name()}
							<span>Vision capabilities</span>
						{/snippet}</DropdownBadge
					>
				{/if}
			</DropdownOption>
		</div>
	{/each}
</div>
