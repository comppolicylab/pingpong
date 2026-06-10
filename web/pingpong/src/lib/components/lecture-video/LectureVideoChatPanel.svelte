<script lang="ts">
	import * as api from '$lib/api';
	import { groupMessageContent, parseTextContent } from '$lib/content';
	import { Button, Tooltip, Avatar } from 'flowbite-svelte';
	import {
		RefreshOutline,
		ServerOutline,
		MessageDotsOutline,
		VolumeUpSolid,
		VolumeMuteSolid,
		PlaySolid,
		ReplyOutline
	} from 'flowbite-svelte-icons';
	import Logo from '$lib/components/Logo.svelte';
	import Markdown from '$lib/components/Markdown.svelte';
	import ChatInput, {
		type ChatInputHandle,
		type ChatInputMessage
	} from '$lib/components/ChatInput.svelte';
	import CodeInterpreterGroup from '$lib/components/CodeInterpreterGroup.svelte';
	import FileCitation from '$lib/components/FileCitation.svelte';
	import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
	import FileSearchCallItem from '$lib/components/FileSearchCallItem.svelte';
	import MCPListToolsCallItem from '$lib/components/MCPListToolsCallItem.svelte';
	import MCPServerCallItem from '$lib/components/MCPServerCallItem.svelte';
	import ReasoningCallItem from '$lib/components/ReasoningCallItem.svelte';
	import WebSearchCallItem from '$lib/components/WebSearchCallItem.svelte';
	import { scroll } from '$lib/actions/scroll';
	import type { Message } from '$lib/stores/thread';
	import { tick } from 'svelte';
	import { SvelteMap, SvelteSet } from 'svelte/reactivity';

	let {
		classId,
		threadId,
		messages,
		canFetchMore,
		showInput = true,
		showContinueWatchingPrompt = true,
		canSubmit,
		disabled,
		waiting,
		submitting,
		threadManagerError,
		assistantDeleted,
		canViewAssistant,
		resolvedAssistantVersion,
		version,
		useLatex,
		userTimezone,
		meName,
		meImage,
		assistantIconSrc = '',
		assistantId,
		participants,
		mimeType,
		fetchMoreMessages,
		fetchCodeInterpreterResult,
		onsubmit,
		ondismisserror,
		ttsMuted = false,
		ttsPlaying = false,
		ttsAvailable = false,
		onmutettstoggle,
		oncontinuewatching
	}: {
		classId: number;
		threadId: number;
		messages: Message[];
		canFetchMore: boolean;
		showInput?: boolean;
		showContinueWatchingPrompt?: boolean;
		canSubmit: boolean;
		disabled: boolean;
		waiting: boolean;
		submitting: boolean;
		threadManagerError: string | null;
		assistantDeleted: boolean;
		canViewAssistant: boolean;
		resolvedAssistantVersion: number;
		version: number;
		useLatex: boolean;
		userTimezone: string;
		meName: string;
		meImage: string;
		assistantIconSrc?: string;
		assistantId: number | null;
		participants: api.ThreadParticipants;
		mimeType: api.MimeTypeLookupFn;
		fetchMoreMessages: () => Promise<void>;
		fetchCodeInterpreterResult: (run_id: string, step_id: string) => Promise<unknown>;
		onsubmit?: (message: ChatInputMessage) => void;
		ondismisserror?: () => void;
		ttsMuted?: boolean;
		ttsPlaying?: boolean;
		ttsAvailable?: boolean;
		onmutettstoggle?: () => void;
		oncontinuewatching?: () => Promise<boolean> | boolean;
	} = $props();

	let messagesContainer: HTMLDivElement | null = null;
	let chatInputRef: ChatInputHandle | null = $state(null);
	const dismissedContinuePromptMessageIds = new SvelteSet<string>();
	const continuePromptDecisionByMessageId = new SvelteMap<string, boolean>();
	const starterQuestions = [
		"What's the main idea of this lecture?",
		'Give me a real-world example.',
		"Quiz me on what's been covered so far."
	];

	function isFileCitation(a: api.TextAnnotation): a is api.TextAnnotationFileCitation {
		return a.type === 'file_citation' && a.text === 'responses_v3';
	}

	function processString(dirtyString: string): {
		cleanString: string;
		images: api.ImageProxy[];
	} {
		const jsonPattern = /\{"Rd1IFKf5dl"\s*:\s*\[.*?\]\}/s;
		const match = dirtyString.match(jsonPattern);

		let cleanString = dirtyString;
		let images: api.ImageProxy[] = [];

		if (match) {
			try {
				const userImages = JSON.parse(match[0]);
				images = userImages['Rd1IFKf5dl'] || [];
				cleanString = dirtyString.replace(jsonPattern, '').trim();
			} catch (error) {
				console.error('Failed to parse user images JSON:', error);
			}
		}

		return { cleanString, images };
	}

	const convertImageProxyToInfo = (data: api.ImageProxy[]) => {
		return data.map((image) => {
			const imageAsServerFile = {
				file_id: image.complements ?? '',
				content_type: image.content_type,
				name: image.name
			} as api.ServerFile;
			return {
				state: 'success',
				progress: 100,
				file: { type: image.content_type, name: image.name },
				response: imageAsServerFile,
				promise: Promise.resolve(imageAsServerFile)
			} as api.FileUploadInfo;
		});
	};

	const getShortMessageTimestamp = (timestamp: number) => {
		return new Intl.DateTimeFormat('en-US', {
			hour: 'numeric',
			minute: 'numeric',
			hour12: true,
			timeZone: userTimezone
		}).format(new Date(timestamp * 1000));
	};

	const getMessageTimestamp = (timestamp: number) => {
		return new Intl.DateTimeFormat('en-US', {
			hour: 'numeric',
			minute: 'numeric',
			second: 'numeric',
			day: 'numeric',
			month: 'long',
			year: 'numeric',
			hour12: true,
			timeZoneName: 'short',
			timeZone: userTimezone
		}).format(new Date(timestamp * 1000));
	};

	const getName = (message: api.OpenAIMessage) => {
		if (message.role === 'user') {
			if (message?.metadata?.is_current_user) {
				return meName || 'Me';
			}
			return (message?.metadata?.name as string | undefined) || 'Anonymous User';
		}
		if (assistantId !== null) {
			return participants.assistant[assistantId] || 'PingPong Bot';
		}
		return 'PingPong Bot';
	};

	const getImage = (message: api.OpenAIMessage) => {
		if (message.role === 'user' && message?.metadata?.is_current_user) {
			return meImage || '';
		}
		return '';
	};

	const isLectureContextPending = (message: api.OpenAIMessage) =>
		message.metadata?.lecture_context_pending === true;

	const getThreadImageUrl = (fileId: string) =>
		api.fullPath(`/class/${classId}/thread/${threadId}/image/${fileId}`);

	const getMessageImageUrl = (messageId: string, fileId: string) =>
		api.fullPath(`/class/${classId}/thread/${threadId}/message/${messageId}/image/${fileId}`);

	const getCodeInterpreterImageUrl = (
		message: api.OpenAIMessage,
		item: api.MessageContentCodeOutputImageFile
	) => {
		const fileId = item.image_file.file_id;
		const ciCallId = item.ci_call_id ?? message.metadata?.['ci_call_id'];
		if (version <= 2 && typeof ciCallId === 'string' && ciCallId.length > 0) {
			return api.fullPath(
				`/class/${classId}/thread/${threadId}/ci_call/${ciCallId}/image/${fileId}`
			);
		}
		if (version <= 2) {
			return null;
		}
		return getThreadImageUrl(fileId);
	};

	const messageHasVisibleText = (message: api.OpenAIMessage) =>
		message.content.some(
			(content) => content.type === 'text' && content.text.value.trim().length > 0
		);

	const getFollowupSuggestions = (message: api.OpenAIMessage) => {
		for (let i = message.content.length - 1; i >= 0; i -= 1) {
			const content = message.content[i];
			if (content.type === 'followup_suggestions') {
				return content.suggestions;
			}
		}
		return [];
	};

	let latestMessageId = $derived(messages.at(-1)?.data.id ?? null);
	let latestAssistantMessageId = $derived.by(() => {
		const latestMessage = messages.at(-1)?.data;
		if (!latestMessage || latestMessage.role !== 'assistant') {
			return null;
		}
		if (isLectureContextPending(latestMessage) || !messageHasVisibleText(latestMessage)) {
			return null;
		}
		return latestMessage.id;
	});

	const isLatestStreamedAssistantResponse = (message: Message) =>
		message.streamedInSession === true &&
		message.data.id === latestMessageId &&
		message.data.id === latestAssistantMessageId;

	const canLatchContinuePromptDecision = (message: Message) =>
		isLatestStreamedAssistantResponse(message) && !waiting && !submitting;

	const getVisibleFollowupSuggestions = (message: Message) => {
		if (
			!showInput ||
			!canSubmitChatText ||
			assistantDeleted ||
			!canViewAssistant ||
			message.data.id !== latestAssistantMessageId
		) {
			return [];
		}
		return getFollowupSuggestions(message.data);
	};

	let canShowStarterQuestions = $derived(showInput && !assistantDeleted && canViewAssistant);
	let canSubmitChatText = $derived(
		canShowStarterQuestions && canSubmit && !disabled && !waiting && !submitting
	);

	const submitChatText = (message: string) => {
		if (!onsubmit || !canSubmitChatText) {
			return;
		}
		onsubmit({
			code_interpreter_file_ids: [],
			file_search_file_ids: [],
			vision_file_ids: [],
			visionFileImageDescriptions: [],
			optimisticVisionFiles: [],
			message,
			callback: () => {}
		});
	};

	const evaluateContinuePromptVisibility = () =>
		showInput && showContinueWatchingPrompt && !!oncontinuewatching;

	$effect(() => {
		let cancelled = false;
		const latestMessage = messages.at(-1);
		const latestMessageId = latestMessage?.data.id ?? null;
		const promptVisibilityAtEffectStart = evaluateContinuePromptVisibility();
		if (!latestMessage || !canLatchContinuePromptDecision(latestMessage)) {
			return () => {
				cancelled = true;
			};
		}
		void (async () => {
			await tick();
			if (cancelled) {
				return;
			}
			const currentLatestMessage = messages.at(-1);
			if (
				!currentLatestMessage ||
				currentLatestMessage.data.id !== latestMessageId ||
				!canLatchContinuePromptDecision(currentLatestMessage)
			) {
				return;
			}
			if (!continuePromptDecisionByMessageId.has(latestMessageId)) {
				continuePromptDecisionByMessageId.set(latestMessageId, promptVisibilityAtEffectStart);
			}
			for (const messageId of Array.from(continuePromptDecisionByMessageId.keys())) {
				if (messageId !== latestMessageId) {
					continuePromptDecisionByMessageId.delete(messageId);
				}
			}
			for (const messageId of Array.from(dismissedContinuePromptMessageIds)) {
				if (messageId !== latestMessageId) {
					dismissedContinuePromptMessageIds.delete(messageId);
				}
			}
		})();
		return () => {
			cancelled = true;
		};
	});

	const shouldShowContinueWatchingPrompt = (message: Message) =>
		evaluateContinuePromptVisibility() &&
		isLatestStreamedAssistantResponse(message) &&
		continuePromptDecisionByMessageId.get(message.data.id) === true &&
		!dismissedContinuePromptMessageIds.has(message.data.id);

	let continueWatchingPromptScrollKey = $derived.by(() => {
		const latestMessage = messages.at(-1);
		if (!latestMessage || !shouldShowContinueWatchingPrompt(latestMessage)) {
			return null;
		}
		return `continue-watching-${latestMessage.data.id}`;
	});

	function dismissContinueWatchingPrompt(message: Message) {
		dismissedContinuePromptMessageIds.add(message.data.id);
	}

	async function continueWatching(message: Message) {
		try {
			const didResume = (await oncontinuewatching?.()) ?? true;
			if (didResume) {
				dismissContinueWatchingPrompt(message);
			}
		} catch {
			// Keep prompt visible so the user can retry.
		}
	}

	function askAnotherQuestion(message: Message) {
		dismissContinueWatchingPrompt(message);
		chatInputRef?.focus();
	}
</script>

<div
	class="flex h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl"
>
	<div
		class="min-h-0 flex-1 overflow-y-auto px-4 py-4"
		bind:this={messagesContainer}
		use:scroll={{
			messages,
			threadId,
			streaming: submitting || waiting,
			tailContentKey: continueWatchingPromptScrollKey
		}}
	>
		{#if canFetchMore}
			<div class="mb-4 flex justify-center">
				<Button size="sm" class="text-sky-600 hover:text-sky-800" onclick={fetchMoreMessages}>
					<RefreshOutline class="me-2 h-3 w-3" /> Load earlier messages ...
				</Button>
			</div>
		{/if}
		{#if !canFetchMore && messages.length === 0}
			<div class="flex h-full min-h-48 items-center justify-center px-4 py-8">
				<div class="flex w-full max-w-sm flex-col items-center text-center">
					<div
						class="mb-3 flex size-12 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-400"
					>
						<MessageDotsOutline class="size-6" />
					</div>
					<h2 class="text-sm font-semibold text-slate-900">Ask about this lecture</h2>
					<p class="mt-1 text-sm text-slate-500">Try a starter question or type your own.</p>
					{#if canShowStarterQuestions}
						<div
							class="mt-4 flex w-full flex-col gap-1.5"
							role="group"
							aria-label="Starter questions"
						>
							{#each starterQuestions as question (question)}
								<button
									type="button"
									class="group flex w-full items-center justify-between gap-2 rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-left text-sm text-slate-700 transition hover:border-sky-300 hover:bg-sky-50 hover:text-sky-800 focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-1 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
									disabled={!canSubmitChatText}
									onclick={() => submitChatText(question)}
								>
									<span>{question}</span>
									<ReplyOutline
										class="size-3.5 shrink-0 -scale-x-100 text-slate-400 transition group-hover:text-sky-600"
										aria-hidden="true"
									/>
								</button>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/if}
		{#each messages as message (message.data.id)}
			<div class="mx-auto flex max-w-4xl gap-x-3 px-2 py-4">
				<div class="shrink-0">
					{#if message.data.role === 'user'}
						<Avatar size="sm" src={getImage(message.data)} />
					{:else if assistantIconSrc}
						<img
							src={assistantIconSrc}
							alt="Disagreement Project"
							class="size-8 rounded-full object-cover"
						/>
					{:else}
						<Logo size={8} />
					{/if}
				</div>
				<div class="w-full max-w-full">
					<div class="mt-1 mb-2 flex flex-wrap items-center gap-2 font-semibold text-blue-dark-40">
						<span class="flex items-center gap-2">{getName(message.data)}</span>
						<span
							class="ml-1 text-xs font-normal text-gray-500 hover:underline"
							id={`short-timestamp-${message.data.id}`}
							>{getShortMessageTimestamp(message.data.created_at)}</span
						>
					</div>
					<Tooltip triggeredBy={`#short-timestamp-${message.data.id}`}>
						{getMessageTimestamp(message.data.created_at)}
					</Tooltip>
					{#if isLectureContextPending(message.data)}
						<p class="shimmer text-sm">Thinking</p>
					{/if}
					{#each groupMessageContent(message.data.content) as block (block.key)}
						{#if block.type === 'mcp_group'}
							<div class="my-3">
								<div class="flex items-center gap-2 text-gray-600">
									<ServerOutline class="h-4 w-4 text-gray-600" />
									<span class="text-xs font-medium tracking-wide uppercase"
										>{block.serverLabel}</span
									>
								</div>
								<div class="mt-2 ml-2 border-l border-gray-200 pl-4">
									{#each block.items as item (item.step_id)}
										{#if item.type === 'mcp_server_call'}
											<MCPServerCallItem content={item} showServerLabel={false} compact={true} />
										{:else if item.type === 'mcp_list_tools_call'}
											<MCPListToolsCallItem content={item} showServerLabel={false} compact={true} />
										{/if}
									{/each}
								</div>
							</div>
						{:else if block.type === 'ci_group'}
							<CodeInterpreterGroup
								stateKey={`${message.data.run_id ?? message.data.id}:${block.key}`}
								items={block.items}
								streaming={isLatestStreamedAssistantResponse(message) &&
									(submitting || waiting) &&
									block.isLast}
								imageUrl={(item) => getCodeInterpreterImageUrl(message.data, item)}
								onFetch={fetchCodeInterpreterResult}
							/>
						{:else}
							{@const content = block.content}
							{#if content.type === 'text'}
								{@const { cleanString, images } = processString(content.text.value)}
								{@const imageInfo = convertImageProxyToInfo(images)}
								{@const quoteCitations = (content.text.annotations ?? []).filter(isFileCitation)}
								{@const parsedTextContent = parseTextContent(
									{ value: cleanString, annotations: content.text.annotations },
									version,
									api.fullPath(`/class/${classId}/thread/${threadId}`),
									content.source_message_id || message.data.id
								)}
								<div class="leading-6">
									<Markdown
										content={parsedTextContent.content}
										inlineWebSources={parsedTextContent.inlineWebSources}
										syntax={true}
										latex={useLatex}
									/>
								</div>
								{#if quoteCitations.length > 0}
									<div class="flex flex-wrap gap-2">
										{#each quoteCitations as citation (citation.file_citation.file_id)}
											<FileCitation
												name={citation.file_citation.file_name}
												quote={citation.file_citation.quote}
											/>
										{/each}
									</div>
								{/if}
								{#if imageInfo.length > 0}
									<div class="flex flex-wrap gap-2">
										{#each imageInfo as image (image.response && 'file_id' in image.response ? image.response.file_id : image.file.name)}
											<FilePlaceholder
												info={image}
												purpose="vision"
												{mimeType}
												preventDeletion={true}
												on:delete={() => {}}
											/>
										{/each}
									</div>
								{/if}
							{:else if content.type === 'file_search_call'}
								<FileSearchCallItem {content} />
							{:else if content.type === 'web_search_call'}
								<WebSearchCallItem {content} />
							{:else if content.type === 'mcp_server_call'}
								<MCPServerCallItem {content} />
							{:else if content.type === 'mcp_list_tools_call'}
								<MCPListToolsCallItem {content} />
							{:else if content.type === 'reasoning'}
								<ReasoningCallItem {content} />
							{:else if content.type === 'image_file'}
								<div class="w-full leading-6">
									<img
										class="img-attachment m-auto"
										src={version <= 2
											? getMessageImageUrl(
													content.source_message_id || message.data.id,
													content.image_file.file_id
												)
											: getThreadImageUrl(content.image_file.file_id)}
										alt="Conversation attachment"
									/>
								</div>
							{/if}
						{/if}
					{/each}
					{#each [{ key: message.data.id, suggestions: getVisibleFollowupSuggestions(message) }] as followupGroup (followupGroup.key)}
						{#if followupGroup.suggestions.length > 0}
							<div
								class="mt-1 flex flex-col items-stretch"
								role="group"
								aria-label="Suggested follow-up responses"
							>
								{#each followupGroup.suggestions as suggestion, i (i)}
									<button
										type="button"
										class="group flex items-center gap-1.5 py-1.5 text-left text-sm text-gray-500 transition hover:text-gray-700 focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-1 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 {i >
										0
											? 'border-t border-gray-200'
											: ''}"
										disabled={!canSubmitChatText}
										onclick={() => submitChatText(suggestion)}
									>
										<ReplyOutline
											class="h-3.5 w-3.5 shrink-0 -scale-x-100 text-gray-400 transition group-hover:text-gray-700"
											aria-hidden="true"
										/>
										<span>{suggestion}</span>
									</button>
								{/each}
							</div>
						{/if}
					{/each}
					{#if shouldShowContinueWatchingPrompt(message)}
						<div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1" aria-live="polite">
							<button
								type="button"
								class="inline-flex items-center gap-1.5 rounded-full bg-orange px-3 py-1 text-sm font-medium text-white transition hover:bg-orange-dark focus:outline-none"
								onclick={() => void continueWatching(message)}
							>
								<PlaySolid class="h-3 w-3" />
								Continue watching
							</button>
							<button
								type="button"
								class="text-sm text-slate-500 transition hover:text-slate-700"
								onclick={() => askAnotherQuestion(message)}
							>
								Ask another question
							</button>
						</div>
					{/if}
				</div>
			</div>
		{/each}
	</div>
	{#if showInput}
		<div class="border-t border-slate-200 px-4 pt-1 pb-3">
			<div class="relative mx-auto flex w-full max-w-4xl flex-col">
				{#if ttsAvailable}
					<div class="flex items-center justify-end gap-2 px-1 pb-1">
						<button
							class="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs transition-colors {ttsMuted
								? 'bg-gray-100 text-gray-500'
								: 'bg-sky-50 text-sky-600'}"
							onclick={() => {
								onmutettstoggle?.();
							}}
							title={ttsMuted ? 'Unmute voice' : 'Mute voice'}
						>
							{#if ttsMuted}
								<VolumeMuteSolid class="h-3.5 w-3.5" />
								<span>Muted</span>
							{:else}
								<VolumeUpSolid class="h-3.5 w-3.5" />
								<span>{ttsPlaying ? 'Speaking' : 'Voice on'}</span>
							{/if}
						</button>
					</div>
				{/if}
				<ChatInput
					bind:this={chatInputRef}
					{mimeType}
					maxSize={0}
					attachments={[]}
					{threadManagerError}
					visionAcceptedFiles={null}
					fileSearchAcceptedFiles={null}
					codeInterpreterAcceptedFiles={null}
					visionSupportOverride={undefined}
					useImageDescriptions={false}
					{assistantDeleted}
					{canViewAssistant}
					{canSubmit}
					{disabled}
					loading={submitting || waiting}
					fileSearchAttachmentCount={0}
					codeInterpreterAttachmentCount={0}
					upload={null}
					remove={null}
					threadVersion={version}
					assistantVersion={resolvedAssistantVersion}
					bypassedSettingsSections={[]}
					placeholderMessage="Ask about the lecture"
					on:submit={(e) => onsubmit?.(e.detail)}
					on:dismissError={() => ondismisserror?.()}
				/>
			</div>
		</div>
	{/if}
</div>
