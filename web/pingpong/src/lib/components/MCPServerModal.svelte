<script lang="ts">
	import type { MCPAuthType, MCPServerToolInput } from '$lib/api';
	import {
		ArrowUpRightFromSquareOutline,
		EyeOutline,
		EyeSlashOutline
	} from 'flowbite-svelte-icons';
	import {
		Button,
		ButtonGroup,
		Helper,
		Input,
		InputAddon,
		Label,
		Modal,
		Select,
		Textarea,
		type SelectOptionType
	} from 'flowbite-svelte';
	import { createEventDispatcher } from 'svelte';
	import { sadToast } from '$lib/toast';

	export let mcpServerLocalDraft: MCPServerToolInput | null = null;
	export let mcpServerEditIndex: number | null = null;
	export let mcpServerRecordFromServer: MCPServerToolInput | null = null;
	const dispatcher = createEventDispatcher();

	let mcpServerDraft: MCPServerToolInput = mcpServerLocalDraft
		? structuredClone(mcpServerLocalDraft)
		: {
				server_label: undefined,
				server_url: '',
				display_name: '',
				description: '',
				auth_type: 'token',
				authorization_token: '',
				headers: {},
				enabled: true
			};

	let isCreating = mcpServerRecordFromServer === null;
	let showToken = false;

	let serverRecordUsesTokenAuth = mcpServerRecordFromServer?.auth_type === 'token';

	type MCPHeaderEntry = { key: string; value: string };

	const mcpAuthOptions: SelectOptionType<MCPAuthType>[] = [
		{ value: 'token', name: 'Access token/API key' },
		{ value: 'header', name: 'Custom headers' },
		{ value: 'none', name: 'None' }
	];

	const headersToRows = (headers: Record<string, string>): MCPHeaderEntry[] => {
		return Object.entries(headers).map(([key, value]) => ({ key, value }));
	};

	let mcpServerHeaderRows: MCPHeaderEntry[] =
		mcpServerDraft.headers && Object.keys(mcpServerDraft.headers).length > 0
			? headersToRows(mcpServerDraft.headers)
			: [{ key: '', value: '' }];

	const addMcpServerHeaderRow = () => {
		mcpServerHeaderRows = [...mcpServerHeaderRows, { key: '', value: '' }];
	};
	const removeMcpServerHeaderRow = (index: number) => {
		mcpServerHeaderRows = mcpServerHeaderRows.filter((_, i) => i !== index);
	};

	const saveMcpServer = (e: Event) => {
		e.preventDefault();

		// Verify fields
		// Server URL is required
		if (!mcpServerDraft.server_url || mcpServerDraft.server_url.trim() === '') {
			sadToast('Please enter a valid MCP server URL.');
			return;
		}

		// If auth type is token, token is required (unless retaining existing token auth)
		if (
			mcpServerDraft.auth_type === 'token' &&
			!serverRecordUsesTokenAuth &&
			(!mcpServerDraft.authorization_token || mcpServerDraft.authorization_token.trim() === '')
		) {
			sadToast('Please enter an access token/API key for token authentication.');
			return;
		}

		// If auth type is header, at least one header is required
		if (mcpServerDraft.auth_type === 'header') {
			const hasValidHeader = mcpServerHeaderRows.some((row) => row.key.trim() !== '');
			if (!hasValidHeader) {
				sadToast('Please enter at least one valid header for header authentication.');
				return;
			}
		}

		if (mcpServerDraft.auth_type === 'none') {
			mcpServerDraft.authorization_token = '';
			mcpServerDraft.headers = {};
		} else if (mcpServerDraft.auth_type === 'token') {
			mcpServerDraft.headers = {};
		} else if (mcpServerDraft.auth_type === 'header') {
			const headers: Record<string, string> = {};
			mcpServerHeaderRows.forEach((row) => {
				if (row.key.trim() !== '') {
					headers[row.key.trim()] = row.value.trim();
				}
			});
			mcpServerDraft.headers = headers;
			mcpServerDraft.authorization_token = '';
		}
		dispatcher('save', { mcpServer: mcpServerDraft, index: mcpServerEditIndex });
	};
</script>

<Modal size="md" open onclose={() => dispatcher('close')} oncancel={() => dispatcher('close')}>
	<div class="flex flex-col">
		<div class="mx-auto my-10 flex w-2/3 flex-col items-center gap-4 text-center">
			<div
				class="rounded-full border border-gray-200 bg-gradient-to-b from-gray-50 to-gray-100 p-3 text-gray-700"
			>
				<ArrowUpRightFromSquareOutline class="h-6 w-6" />
			</div>
			<div>
				<h2 class="text-xl font-semibold text-gray-900">
					{isCreating ? 'Set up MCP Server' : 'Edit MCP Server'}
				</h2>
			</div>
		</div>
		<div class="mx-auto flex w-2/3 flex-1 flex-col gap-4 px-1">
			<div class="flex flex-col gap-2">
				<Label for="mcp-server-url">URL</Label>
				<Helper class="-mt-1">Only use MCP servers you trust and verify.</Helper>
				<Input
					id="mcp-server-url"
					name="mcp-server-url"
					type="url"
					placeholder="https://mcp.example.com"
					bind:value={mcpServerDraft.server_url}
				/>
			</div>
			<div class="flex flex-col gap-2">
				<Label for="mcp-server-display-name">Server Name</Label>
				<Helper class="-mt-1">Will be displayed when the assistant uses this MCP server.</Helper>
				<Input
					id="mcp-server-display-name"
					name="mcp-server-display-name"
					type="text"
					placeholder="My MCP Server"
					bind:value={mcpServerDraft.display_name}
				/>
			</div>
			<div class="flex flex-col gap-2">
				<Label for="mcp-server-description">
					Description <span class="text-xs text-gray-500">(optional)</span>
				</Label>
				<Helper class="-mt-1"
					>Add a description to help the assistant understand when to use this MCP server.</Helper
				>
				<Textarea
					id="mcp-server-description"
					name="mcp-server-description"
					rows={2}
					placeholder="MCP server for handling advanced queries."
					bind:value={mcpServerDraft.description}
				/>
			</div>
			<div class="flex flex-col gap-2">
				<Label for="mcp-auth-type" class="flex items-center gap-1">Authentication</Label>
				<Select
					id="mcp-auth-type"
					name="mcp-auth-type"
					items={mcpAuthOptions}
					bind:value={mcpServerDraft.auth_type}
				/>
			</div>
			{#if mcpServerDraft.auth_type === 'token'}
				<div class="flex flex-col gap-2">
					<Label for="mcp-auth-token">Access token/API key</Label>
					<Helper
						>Your token will be provided in the Authorization header. <code
							>Authorization: Bearer &lt;token&gt;</code
						></Helper
					>
					<ButtonGroup class="w-full">
						<InputAddon>
							<button onclick={() => (showToken = !showToken)}>
								{#if showToken}
									<EyeOutline class="h-6 w-6" />
								{:else}
									<EyeSlashOutline class="h-6 w-6" />
								{/if}
							</button>
						</InputAddon>
						<Input
							id="mcp-auth-token"
							name="mcp-auth-token"
							type={showToken ? 'text' : 'password'}
							placeholder={serverRecordUsesTokenAuth
								? 'Leave blank to keep the existing token'
								: 'Add your access token'}
							bind:value={mcpServerDraft.authorization_token}
						/>
					</ButtonGroup>

					{#if serverRecordUsesTokenAuth}
						<Helper class="-mt-1">Leave blank to keep the existing token.</Helper>
					{:else}
						<Helper class="-mt-1">Required for token authentication.</Helper>
					{/if}
				</div>
			{/if}
			{#if mcpServerDraft.auth_type === 'header'}
				<div class="flex flex-col gap-2">
					<Label>Headers</Label>
					<div class="flex flex-col gap-2">
						{#each mcpServerHeaderRows as row, index (index)}
							<div class="flex flex-col gap-2 sm:flex-row sm:items-center">
								<div class="flex-1">
									<Input placeholder="header" bind:value={row.key} />
								</div>
								<span class="hidden text-gray-400 sm:block">:</span>
								<div class="flex-1">
									<Input placeholder="value" bind:value={row.value} />
								</div>
								<Button
									type="button"
									size="xs"
									color="light"
									class="text-red-600 sm:ml-1"
									onclick={() => removeMcpServerHeaderRow(index)}
									disabled={mcpServerHeaderRows.length === 1}>Remove</Button
								>
							</div>
						{/each}
						<Button
							type="button"
							size="xs"
							color="light"
							class="w-fit"
							onclick={addMcpServerHeaderRow}>Add header</Button
						>
					</div>
				</div>
			{/if}
		</div>
		<div class="mt-6 flex w-full items-end justify-between">
			<Button type="button" color="light" onclick={() => dispatcher('close')}>Cancel</Button>
			<Button type="submit" color="blue" onclick={saveMcpServer}>Save</Button>
		</div>
	</div>
</Modal>
