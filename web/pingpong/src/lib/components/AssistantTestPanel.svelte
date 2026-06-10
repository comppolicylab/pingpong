<script lang="ts">
	import { Button, Spinner, Tooltip } from 'flowbite-svelte';
	import { CloseOutline, RefreshOutline } from 'flowbite-svelte-icons';
	import { DoubleBounce } from 'svelte-loading-spinners';
	import { createEventDispatcher } from 'svelte';
	import * as api from '$lib/api';
	import { errorMessage } from '$lib/errors';
	import { scroll } from '$lib/actions/scroll';
	import { parseTextContent } from '$lib/content';
	import { readable } from 'svelte/store';
	import { ThreadManager, type ErrorWithSent, type Message } from '$lib/stores/thread';
	import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
	import Logo from '$lib/components/Logo.svelte';
	import Markdown from '$lib/components/Markdown.svelte';
	import FileSearchCallItem from '$lib/components/FileSearchCallItem.svelte';
	import MCPListToolsCallItem from '$lib/components/MCPListToolsCallItem.svelte';
	import MCPServerCallItem from '$lib/components/MCPServerCallItem.svelte';
	import ReasoningCallItem from '$lib/components/ReasoningCallItem.svelte';
	import WebSearchCallItem from '$lib/components/WebSearchCallItem.svelte';

	const dispatcher = createEventDispatcher<{ close: void }>();

	export let classId: number;
	export let assistantId: number;
	export let userId: number;
	export let assistantName = 'Assistant';
	export let useLatex = false;
	/**
	 * Returns the current (possibly unsaved) editor settings to test with.
	 */
	export let getRunSettingsOverrides: () => api.RunSettingsOverrides;
	/**
	 * Returns the tools currently enabled in the editor. Tools are fixed when
	 * the test conversation starts; restart the conversation to change them.
	 */
	export let getToolsAvailable: () => api.Tool[];

	let threadMgr: ThreadManager | null = null;
	let threadId: number | null = null;
	let creating = false;
	let createError: string | null = null;
	let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

	const noMessages = readable<Message[]>([]);
	const notBusy = readable(false);
	const noError = readable<ErrorWithSent | null>(null);
	$: messages = threadMgr?.messages ?? noMessages;
	$: waiting = threadMgr?.waiting ?? notBusy;
	$: submitting = threadMgr?.submitting ?? notBusy;
	$: managerError = threadMgr?.error ?? noError;
	$: busy = creating || $waiting || $submitting;

	const validateOverrides = (overrides: api.RunSettingsOverrides): string | null => {
		if (!overrides.instructions || overrides.instructions.trim().length < 3) {
			return 'Add instructions (at least 3 characters) before testing.';
		}
		if (!overrides.model) {
			return 'Select a model before testing.';
		}
		return null;
	};

	const startThread = async (form: ChatInputMessage, overrides: api.RunSettingsOverrides) => {
		creating = true;
		createError = null;
		try {
			const newThreadOpts = api.explodeResponse(
				await api.createThread(fetch, classId, {
					assistant_id: assistantId,
					message: form.message,
					tools_available: getToolsAvailable(),
					timezone: userTimezone,
					is_test: true,
					run_settings_overrides: overrides
				})
			);
			threadId = newThreadOpts.thread.id;
			const threadData = await api.getThread(fetch, classId, threadId);
			const mgr = new ThreadManager(fetch, classId, threadId, threadData, 'chat', userTimezone);
			mgr.getRunSettingsOverrides = () => {
				const current = getRunSettingsOverrides();
				return validateOverrides(current) ? null : current;
			};
			threadMgr = mgr;
			form.callback({ success: true, errorMessage: null, message_sent: true });
		} catch (e) {
			createError = errorMessage(e, 'Something went wrong while starting the test conversation.');
			form.callback({ success: false, errorMessage: createError, message_sent: false });
		} finally {
			creating = false;
		}
	};

	const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
		const form = e.detail;
		const overrides = getRunSettingsOverrides();
		const validationError = validateOverrides(overrides);
		if (validationError) {
			createError = validationError;
			form.callback({ success: false, errorMessage: validationError, message_sent: false });
			return;
		}
		createError = null;
		if (!threadMgr) {
			await startThread(form, overrides);
			return;
		}
		await threadMgr.postMessage(userId, form.message, form.callback);
	};

	const restart = () => {
		threadMgr = null;
		threadId = null;
		createError = null;
	};

	const handleDismissError = () => {
		createError = null;
		threadMgr?.dismissError();
	};

	const getName = (message: api.OpenAIMessage) => (message.role === 'user' ? 'You' : assistantName);
</script>

<div class="flex h-full min-h-0 flex-col rounded-lg border border-gray-200 bg-white shadow-sm">
	<div class="flex items-center justify-between gap-2 border-b border-gray-200 px-4 py-3">
		<div class="min-w-0">
			<div class="truncate text-sm font-semibold text-blue-dark-40">Test conversation</div>
			<div class="truncate text-xs text-gray-500">
				Responses use your current settings, even if unsaved.
			</div>
		</div>
		<div class="flex shrink-0 items-center gap-1">
			{#if threadMgr}
				<Button
					id="test-panel-restart"
					size="xs"
					color="alternative"
					disabled={busy}
					onclick={restart}
				>
					<RefreshOutline class="me-1 h-4 w-4" />
					Restart
				</Button>
				<Tooltip triggeredBy="#test-panel-restart"
					>Start over with the latest settings (including tool changes)</Tooltip
				>
			{/if}
			<Button size="xs" color="alternative" onclick={() => dispatcher('close')}>
				<CloseOutline class="h-4 w-4" />
				<span class="sr-only">Close test panel</span>
			</Button>
		</div>
	</div>

	{#if threadMgr && threadId !== null}
		<div
			class="min-h-0 grow overflow-y-auto"
			use:scroll={{
				messages: $messages,
				threadId,
				streaming: !!($waiting || $submitting)
			}}
		>
			{#each $messages as message (message.data.id)}
				<div class="flex gap-x-3 px-4 py-3">
					<div class="shrink-0">
						{#if message.data.role === 'user'}
							<div
								class="flex size-7 items-center justify-center rounded-full bg-blue-dark-30 text-xs font-semibold text-white"
							>
								{getName(message.data).slice(0, 1)}
							</div>
						{:else}
							<Logo size={7} />
						{/if}
					</div>
					<div class="w-full min-w-0">
						<div class="mb-1 text-sm font-semibold text-blue-dark-40">
							{getName(message.data)}
						</div>
						{#each message.data.content || [] as content, contentIndex (contentIndex)}
							{#if content.type === 'text'}
								{@const parsedTextContent = parseTextContent(
									content.text,
									3,
									api.fullPath(`/class/${classId}/thread/${threadId}`),
									content.source_message_id || message.data.id
								)}
								<div class="text-sm leading-6">
									<Markdown
										content={parsedTextContent.content}
										inlineWebSources={parsedTextContent.inlineWebSources}
										syntax={true}
										latex={useLatex}
									/>
								</div>
							{:else if content.type === 'reasoning'}
								<ReasoningCallItem {content} />
							{:else if content.type === 'file_search_call'}
								<FileSearchCallItem {content} />
							{:else if content.type === 'web_search_call'}
								<WebSearchCallItem {content} />
							{:else if content.type === 'mcp_server_call'}
								<MCPServerCallItem {content} />
							{:else if content.type === 'mcp_list_tools_call'}
								<MCPListToolsCallItem {content} />
							{:else if content.type === 'code'}
								<pre
									style="white-space: pre-wrap;"
									class="my-2 rounded bg-gray-50 p-2 text-xs text-black">{content.code}</pre>
							{:else if content.type === 'code_output_logs'}
								<pre
									style="white-space: pre-wrap;"
									class="my-2 rounded bg-gray-50 p-2 text-xs text-black">{content.logs}</pre>
							{/if}
						{/each}
					</div>
				</div>
			{/each}
			{#if $waiting || $submitting}
				<div class="flex gap-x-3 px-4 py-3">
					<div class="shrink-0"><Logo size={7} /></div>
					<div class="flex items-center pt-1">
						<DoubleBounce color="#577692" size="20" unit="px" />
					</div>
				</div>
			{/if}
		</div>
	{:else}
		<div class="flex min-h-0 grow flex-col items-center justify-center gap-2 px-6 text-center">
			{#if creating}
				<Spinner size="6" />
				<div class="text-sm text-gray-500">Starting test conversation…</div>
			{:else}
				<Logo size={10} />
				<div class="text-sm font-medium text-blue-dark-40">Try out your assistant</div>
				<div class="text-xs text-gray-500">
					Send a message to test the assistant with the settings currently in the editor — no need
					to save first. Edit the prompt or model between messages to compare responses.
				</div>
			{/if}
		</div>
	{/if}

	<div class="border-t border-gray-200 p-3">
		<ChatInput
			mimeType={() => undefined}
			canSubmit={true}
			disabled={busy}
			loading={busy}
			threadManagerError={createError || $managerError?.detail || null}
			threadVersion={3}
			assistantVersion={3}
			placeholderMessage="Test your assistant"
			on:submit={handleSubmit}
			on:dismissError={handleDismissError}
		/>
	</div>
</div>
