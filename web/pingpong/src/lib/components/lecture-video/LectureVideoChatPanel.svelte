<script lang="ts">
	import * as api from '$lib/api';
	import { parseTextContent } from '$lib/content';
	import { blur } from 'svelte/transition';
	import { Button, Tooltip, Avatar, Accordion, AccordionItem } from 'flowbite-svelte';
	import {
		RefreshOutline,
		CodeOutline,
		ServerOutline,
		TerminalOutline,
		VolumeUpSolid,
		VolumeMuteSolid
	} from 'flowbite-svelte-icons';
	import { DoubleBounce } from 'svelte-loading-spinners';
	import Logo from '$lib/components/Logo.svelte';
	import Markdown from '$lib/components/Markdown.svelte';
	import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
	import FileCitation from '$lib/components/FileCitation.svelte';
	import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
	import FileSearchCallItem from '$lib/components/FileSearchCallItem.svelte';
	import MCPListToolsCallItem from '$lib/components/MCPListToolsCallItem.svelte';
	import MCPServerCallItem from '$lib/components/MCPServerCallItem.svelte';
	import ReasoningCallItem from '$lib/components/ReasoningCallItem.svelte';
	import WebSearchCallItem from '$lib/components/WebSearchCallItem.svelte';
	import { scroll } from '$lib/actions/scroll';
	import type { Message } from '$lib/stores/thread';

	let {
		classId,
		threadId,
		messages,
		canFetchMore,
		showInput = true,
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
		assistantId,
		participants,
		mimeType,
		fetchMoreMessages,
		onsubmit,
		ondismisserror,
		ttsMuted = false,
		ttsPlaying = false,
		ttsAvailable = false,
		onmutettstoggle,
		ontextinput,
		ontextpaste
	}: {
		classId: number;
		threadId: number;
		messages: Message[];
		canFetchMore: boolean;
		showInput?: boolean;
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
		assistantId: number | null;
		participants: api.ThreadParticipants;
		mimeType: api.MimeTypeLookupFn;
		fetchMoreMessages: () => Promise<void>;
		onsubmit?: (message: ChatInputMessage) => void;
		ondismisserror?: () => void;
		ttsMuted?: boolean;
		ttsPlaying?: boolean;
		ttsAvailable?: boolean;
		onmutettstoggle?: () => void;
		ontextinput?: (detail: { hasText: boolean }) => void;
		ontextpaste?: (detail: { hasText: boolean }) => void;
	} = $props();

	let messagesContainer: HTMLDivElement | null = null;

	type MCPContent = api.MCPServerCallItem | api.MCPListToolsCallItem;
	type ContentBlock =
		| { type: 'content'; key: string; content: api.Content }
		| { type: 'mcp_group'; key: string; serverLabel: string; items: MCPContent[] };

	const isMCPContent = (content: api.Content): content is MCPContent => {
		return content.type === 'mcp_server_call' || content.type === 'mcp_list_tools_call';
	};

	const getMCPServerKey = (content: MCPContent) => {
		return content.server_label || content.server_name || 'mcp';
	};

	const groupMessageContent = (contents: api.Content[]): ContentBlock[] => {
		const blocks: ContentBlock[] = [];
		let index = 0;

		while (index < contents.length) {
			const content = contents[index];
			if (!isMCPContent(content)) {
				blocks.push({ type: 'content', key: `content-${index}`, content });
				index += 1;
				continue;
			}

			const serverKey = getMCPServerKey(content);
			const items: MCPContent[] = [content];
			let cursor = index + 1;
			while (cursor < contents.length) {
				const next = contents[cursor];
				if (!isMCPContent(next) || getMCPServerKey(next) !== serverKey) {
					break;
				}
				items.push(next);
				cursor += 1;
			}

			if (items.length > 1) {
				const label = items[0].server_name || items[0].server_label || 'MCP server';
				blocks.push({
					type: 'mcp_group',
					key: `mcp-group-${serverKey}-${index}`,
					serverLabel: label,
					items
				});
			} else {
				blocks.push({ type: 'content', key: `content-${index}`, content });
			}

			index = cursor;
		}

		return blocks;
	};

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

	const getThreadImageUrl = (fileId: string) =>
		api.fullPath(`/class/${classId}/thread/${threadId}/image/${fileId}`);

	const getMessageImageUrl = (messageId: string, fileId: string) =>
		api.fullPath(`/class/${classId}/thread/${threadId}/message/${messageId}/image/${fileId}`);

	const getCodeInterpreterImageUrl = (message: api.OpenAIMessage, fileId: string) => {
		const ciCallId = message.metadata?.['ci_call_id'];
		if (version <= 2 && typeof ciCallId === 'string' && ciCallId.length > 0) {
			return api.fullPath(
				`/class/${classId}/thread/${threadId}/ci_call/${ciCallId}/image/${fileId}`
			);
		}
		return getThreadImageUrl(fileId);
	};
</script>

<div
	class="flex h-full min-h-0 flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl"
>
	<div
		class="min-h-0 flex-1 overflow-y-auto px-4 py-4"
		bind:this={messagesContainer}
		use:scroll={{ messages, threadId, streaming: submitting || waiting }}
	>
		{#if canFetchMore}
			<div class="mb-4 flex justify-center">
				<Button size="sm" class="text-sky-600 hover:text-sky-800" onclick={fetchMoreMessages}>
					<RefreshOutline class="me-2 h-3 w-3" /> Load earlier messages ...
				</Button>
			</div>
		{/if}
		{#each messages as message (message.data.id)}
			<div class="mx-auto flex max-w-4xl gap-x-3 px-2 py-4">
				<div class="shrink-0">
					{#if message.data.role === 'user'}
						<Avatar size="sm" src={getImage(message.data)} />
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
							{:else if content.type === 'code'}
								<Accordion flush>
									<AccordionItem>
										<span slot="header">
											<div class="flex flex-row items-center space-x-2">
												<div><CodeOutline size="lg" /></div>
												<div>Code Interpreter Code</div>
											</div>
										</span>
										<pre style="white-space: pre-wrap;" class="text-black">{content.code}</pre>
									</AccordionItem>
								</Accordion>
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
							{:else if content.type === 'code_output_image_file'}
								<div class="w-full leading-6">
									<img
										class="img-attachment m-auto"
										src={getCodeInterpreterImageUrl(message.data, content.image_file.file_id)}
										alt="Attachment generated by the assistant"
									/>
								</div>
							{:else if content.type === 'code_output_image_url'}
								<div class="w-full leading-6">
									<img
										class="img-attachment m-auto"
										src={content.url}
										alt="Attachment generated by the assistant"
									/>
								</div>
							{:else if content.type === 'code_output_logs'}
								<Accordion flush>
									<AccordionItem>
										<span slot="header">
											<div class="flex flex-row items-center space-x-2">
												<div><TerminalOutline size="lg" /></div>
												<div>Output Logs</div>
											</div>
										</span>
										<div class="w-full leading-6">
											<pre style="white-space: pre-wrap;" class="text-black">{content.logs}</pre>
										</div>
									</AccordionItem>
								</Accordion>
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
				</div>
			</div>
		{/each}
	</div>
	{#if showInput}
		<div class="border-t border-slate-200 px-4 pt-1 pb-3">
			<div class="relative mx-auto flex w-full max-w-4xl flex-col">
				{#if waiting || submitting}
					<div class="absolute -top-10 flex w-full justify-center" transition:blur={{ amount: 10 }}>
						<DoubleBounce color="#0ea5e9" size="30" />
					</div>
				{/if}
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
					on:submit={(e) => onsubmit?.(e.detail)}
					on:dismissError={() => ondismisserror?.()}
					on:textinput={(e) => ontextinput?.(e.detail)}
					on:textpaste={(e) => ontextpaste?.(e.detail)}
				/>
			</div>
		</div>
	{/if}
</div>
