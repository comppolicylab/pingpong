<script lang="ts">
	import { run } from 'svelte/legacy';

	import { slide } from 'svelte/transition';
	import { ChevronDownOutline, ServerOutline } from 'flowbite-svelte-icons';
	import { Modal } from 'flowbite-svelte';
	import type { MCPListToolsCallItem, MCPListToolsTool, MCPToolError } from '$lib/api';

	interface Props {
		content: MCPListToolsCallItem;
		forceOpen?: boolean;
		showServerLabel?: boolean;
		compact?: boolean;
	}

	let {
		content,
		forceOpen = false,
		showServerLabel = true,
		compact = false
	}: Props = $props();

	let open = $state(false);
	let previousOpen: boolean | null = $state(null);
	let toolModalOpen = $state(false);
	let activeTool: MCPListToolsTool | null = $state(null);

	$effect(() => {
		if (forceOpen) {
			if (previousOpen === null) {
				previousOpen = open;
			}
			open = true;
		} else if (previousOpen !== null) {
			open = previousOpen;
			previousOpen = null;
		}
	});

	const toggle = () => (open = !open);

	const openToolModal = (tool: MCPListToolsTool) => {
		activeTool = tool;
		toolModalOpen = true;
	};

	const formatPayload = (payload?: Record<string, unknown> | null) => {
		if (!payload) return '';
		try {
			return JSON.stringify(payload, null, 2);
		} catch {
			return '';
		}
	};

	const formatError = (error?: MCPToolError | null) => {
		if (!error) return '';
		if (typeof error === 'string') return error;
		return JSON.stringify(error, null, 2);
	};

	let serverLabel = $derived(content.server_name || content.server_label || 'MCP server');
	let errorPayload = $derived(formatError(content.error));
	let hasTools = $derived(!!content.tools && content.tools.length > 0);
	let statusLabel =
		$derived(content.status === 'completed'
			? `Listed tools${open ? '...' : ''}`
			: content.status === 'failed'
				? 'List tools failed'
				: content.status === 'incomplete'
					? 'List tools was canceled'
					: 'Listing tools...');

	let statusClasses =
		$derived(content.status === 'in_progress' || content.status === 'calling'
			? 'text-sm font-medium shimmer'
			: content.status === 'failed'
				? 'text-sm font-medium text-yellow-600'
				: content.status === 'incomplete'
					? 'text-sm font-medium text-yellow-600'
					: 'text-sm font-medium text-gray-600');
</script>

<Modal
	bind:open={toolModalOpen}
	title={activeTool ? `${serverLabel} - ${activeTool.name}` : `${serverLabel} tool`}
	autoclose
	outsideclose
	dismissable
>
	{#if activeTool}
		<div class="flex flex-col gap-4">
			<div>
				<h5 class="mb-1 text-sm font-medium text-gray-700">Description</h5>
				<p class="text-sm text-gray-600">{activeTool.description || 'No description provided.'}</p>
			</div>
			<div>
				<h5 class="mb-1 text-sm font-medium text-gray-700">Parameters</h5>
				{#if activeTool.input_schema}
					<pre
						class="rounded border border-gray-200 bg-gray-50 px-4 py-3 font-mono text-xs whitespace-pre-wrap text-gray-700">{formatPayload(
							activeTool.input_schema
						)}</pre>
				{:else}
					<p class="text-sm text-gray-500">No parameters available.</p>
				{/if}
			</div>
			{#if activeTool.annotations}
				<div>
					<h5 class="mb-1 text-sm font-medium text-gray-700">Annotations</h5>
					<pre
						class="rounded border border-gray-200 bg-gray-50 px-4 py-3 font-mono text-xs whitespace-pre-wrap text-gray-700">{formatPayload(
							activeTool.annotations
						)}</pre>
				</div>
			{/if}
		</div>
	{/if}
</Modal>

<div class={compact ? 'my-2' : 'my-3'}>
	{#if showServerLabel}
		<div class="flex items-center gap-2 text-gray-600">
			<ServerOutline class="h-4 w-4 text-gray-600" />
			<span class="text-xs font-medium tracking-wide uppercase">{serverLabel}</span>
		</div>
	{/if}
	<div class={showServerLabel ? 'mt-1' : 'mt-0'}>
		{#if hasTools}
			<button type="button" class="flex flex-row items-center gap-1" onclick={toggle}>
				<span class={statusClasses}>{statusLabel}</span>
				{#if open}
					<ChevronDownOutline class="rotate-180 transform text-gray-600" />
				{:else}
					<ChevronDownOutline class="text-gray-600" />
				{/if}
			</button>
		{:else}
			<span class={statusClasses}>{statusLabel}</span>
		{/if}
	</div>

	{#if hasTools}
		{#if open}
			<div
				class="mt-2 ml-2 border-l border-gray-200 pl-4 text-sm font-light text-gray-600"
				transition:slide={{ duration: 250 }}
			>
				{#if errorPayload}
					<div class="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
						{errorPayload}
					</div>
				{/if}
				<div class="flex flex-wrap gap-2">
					{#each content.tools ?? [] as tool, i (tool.name)}
						<button
							type="button"
							class="rounded border border-gray-200 bg-gray-50 px-2 py-1 font-mono text-xs text-gray-700 hover:bg-gray-100"
							onclick={() => openToolModal(tool)}
							transition:slide={{ delay: i * 80, duration: 250 }}
						>
							{tool.name}
						</button>
					{/each}
				</div>
			</div>
		{/if}
	{/if}
</div>

<style lang="css">
	.shimmer {
		color: transparent;
		-webkit-text-fill-color: transparent;
		animation-delay: 0s;
		animation-duration: 2s;
		animation-iteration-count: infinite;
		animation-name: shimmer;
		background: #4b5563 -webkit-gradient(
				linear,
				100% 0,
				0 0,
				from(#5d5d5d),
				color-stop(0.4, #ffffffbf),
				to(#4b5563),
				color-stop(0.6, #ffffffbf),
				to(#4b5563)
			);
		-webkit-background-clip: text;
		background-clip: text;
		background-position: -100% 0;
		background-position: unset top;
		background-repeat: no-repeat;
		background-size: 50% 200%;
	}

	@keyframes shimmer {
		0% {
			background-position: -100% 0;
		}
		100% {
			background-position: 250% 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.shimmer {
			animation: none;
		}
	}

	.shimmer:hover {
		-webkit-text-fill-color: #374151;
		color: #374151;
		background: 0 0;
	}
</style>
