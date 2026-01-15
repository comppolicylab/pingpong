<script lang="ts">
	import { slide } from 'svelte/transition';
	import { Tooltip } from 'flowbite-svelte';
	import { ChevronDownOutline, QuestionCircleOutline, ServerOutline } from 'flowbite-svelte-icons';
	import type { MCPServerCallItem, MCPToolError } from '$lib/api';

	interface Props {
		content: MCPServerCallItem;
		forceOpen?: boolean;
		showServerLabel?: boolean;
		compact?: boolean;
	}

	let { content, forceOpen = false, showServerLabel = true, compact = false }: Props = $props();

	let open = $state(false);
	let previousOpen: boolean | null = $state(null);
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

	const formatPayload = (payload?: string | null) => {
		if (!payload) return '';
		try {
			return JSON.stringify(JSON.parse(payload), null, 2);
		} catch {
			return payload;
		}
	};

	const formatError = (error?: MCPToolError | null) => {
		if (!error) return '';
		if (typeof error === 'string') return formatPayload(error);
		return JSON.stringify(error, null, 2);
	};

	let serverLabel = $derived(content.server_name || content.server_label || 'MCP server');
	let toolLabel = $derived(content.tool_name || 'MCP call');
	let requestPayload = $derived(formatPayload(content.arguments));
	let responsePayload = $derived(formatPayload(content.output));
	let errorPayload = $derived(formatError(content.error));
	let hasResult = $derived(!!requestPayload || !!responsePayload || !!errorPayload);

	let statusLabel = $derived(
		content.status === 'completed'
			? `Ran ${toolLabel}${open ? '...' : ''}`
			: content.status === 'failed'
				? `${toolLabel} failed${open ? '...' : ''}`
				: content.status === 'incomplete'
					? `${toolLabel} was canceled`
					: `Calling ${toolLabel}...`
	);

	let statusClasses = $derived(
		content.status === 'in_progress' || content.status === 'calling'
			? 'text-sm font-medium shimmer'
			: content.status === 'failed'
				? 'text-sm font-medium text-yellow-600'
				: content.status === 'incomplete'
					? 'text-sm font-medium text-yellow-600'
					: 'text-sm font-medium text-gray-600'
	);
</script>

<div class={compact ? 'my-2' : 'my-3'}>
	{#if showServerLabel}
		<div class="flex items-center gap-2 text-gray-600">
			<ServerOutline class="h-4 w-4 text-gray-600" />
			<span class="text-xs font-medium tracking-wide uppercase">{serverLabel}</span>
		</div>
	{/if}
	<div class={showServerLabel ? 'mt-1' : 'mt-0'}>
		{#if hasResult}
			<button type="button" class="flex flex-row items-center gap-1" onclick={toggle}>
				<span class={statusClasses}>{statusLabel}</span>
				{#if content.status === 'failed'}
					<span class="inline-flex">
						<QuestionCircleOutline class="h-4 w-4 text-gray-500" />
					</span>
					<Tooltip
						type="custom"
						arrow={false}
						class="z-10 max-w-xs bg-gray-900 px-3 py-2 text-sm font-light text-white"
					>
						This error may be normal. If the assistant made another call that succeeded, there's
						nothing to worry about.
					</Tooltip>
				{/if}
				{#if open}
					<ChevronDownOutline class="rotate-180 transform text-gray-600" />
				{:else}
					<ChevronDownOutline class="text-gray-600" />
				{/if}
			</button>
		{:else}
			<span class="flex flex-row items-center gap-1">
				<span class={statusClasses}>{statusLabel}</span>
				{#if content.status === 'failed'}
					<span class="inline-flex">
						<QuestionCircleOutline class="h-4 w-4 text-gray-600" />
					</span>
					<Tooltip
						type="custom"
						arrow={false}
						class="z-10 max-w-xs bg-gray-900 px-3 py-2 text-center text-sm font-light text-white"
					>
						This error may be normal. If the assistant made another call that succeeded, there's
						nothing to worry about.
					</Tooltip>
				{/if}
			</span>
		{/if}
	</div>

	{#if hasResult}
		{#if open}
			<div
				class="mt-2 ml-2 border-l border-gray-200 pl-4 text-sm font-light text-gray-600"
				transition:slide={{ duration: 250 }}
			>
				{#if requestPayload}
					<div class="pb-3">
						<div class="rounded border border-gray-200 bg-gray-50 px-4 py-3">
							<div class="mb-2 text-xs text-gray-500">Request</div>
							<pre
								class="font-mono text-xs whitespace-pre-wrap text-gray-700">{requestPayload}</pre>
						</div>
					</div>
				{/if}

				{#if responsePayload || errorPayload}
					<div class="pb-3">
						<div class="rounded border border-gray-200 bg-gray-50 px-4 py-3">
							<div class="mb-2 text-xs text-gray-500">{errorPayload ? 'Error' : 'Response'}</div>
							<pre class="font-mono text-xs whitespace-pre-wrap text-gray-700">{errorPayload ||
									responsePayload}</pre>
						</div>
					</div>
				{:else}
					<div class="text-xs text-gray-500">Waiting for response...</div>
				{/if}
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
