<script lang="ts">
	import { navigating, page } from '$app/stores';
	import { beforeNavigate, goto, invalidateAll, afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import {
		getAnonymousSessionToken,
		getAnonymousShareToken,
		hasAnonymousShareToken,
		resetAnonymousSessionToken
	} from '$lib/stores/anonymous';
	import { happyToast, sadToast } from '$lib/toast';
	import { errorMessage } from '$lib/errors';
	import { computeLatestIncidentTimestamps, filterLatestIncidentUpdates } from '$lib/statusUpdates';
	import { blur } from 'svelte/transition';
	import {
		Accordion,
		AccordionItem,
		Avatar,
		Button,
		Card,
		Dropdown,
		DropdownDivider,
		DropdownItem,
		Modal,
		Span,
		Spinner,
		Tooltip
	} from 'flowbite-svelte';
	import { DoubleBounce } from 'svelte-loading-spinners';
	import Markdown from '$lib/components/Markdown.svelte';
	import Logo from '$lib/components/Logo.svelte';
	import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
	import ChatDropOverlay from '$lib/components/ChatDropOverlay.svelte';
	import DropdownBadge from '$lib/components/DropdownBadge.svelte';
	import AssistantVersionBadge from '$lib/components/AssistantVersionBadge.svelte';
	import {
		RefreshOutline,
		CodeOutline,
		ImageSolid,
		CogOutline,
		EyeOutline,
		EyeSlashOutline,
		LockSolid,
		MicrophoneOutline,
		ChevronSortOutline,
		PlaySolid,
		StopSolid,
		CheckOutline,
		ServerOutline,
		MicrophoneSlashOutline,
		UsersSolid,
		LinkOutline,
		TerminalOutline,
		QuestionCircleOutline
	} from 'flowbite-svelte-icons';
	import { parseTextContent } from '$lib/content';
	import { ThreadManager, type Message } from '$lib/stores/thread';
	import AttachmentDeletedPlaceholder from '$lib/components/AttachmentDeletedPlaceholder.svelte';
	import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
	import { get, writable } from 'svelte/store';
	import ModeratorsTable from '$lib/components/ModeratorsTable.svelte';
	import {
		AUDIO_WORKLET_UNSUPPORTED_MESSAGE,
		base64ToArrayBuffer,
		WavRecorder,
		WavStreamPlayer
	} from '$lib/wavtools/index';
	import type { ExtendedMediaDeviceInfo } from '$lib/wavtools/lib/wav_recorder';
	import { isFirefox } from '$lib/stores/general';
	import Sanitize from '$lib/components/Sanitize.svelte';
	import AudioPlayer from '$lib/components/AudioPlayer.svelte';
	import { tick } from 'svelte';
	import FileCitation from './FileCitation.svelte';
	import StatusErrors from './StatusErrors.svelte';
	import FileSearchCallItem from './FileSearchCallItem.svelte';
	import MCPListToolsCallItem from './MCPListToolsCallItem.svelte';
	import MCPServerCallItem from './MCPServerCallItem.svelte';
	import ReasoningCallItem from './ReasoningCallItem.svelte';
	import WebSearchCallItem from './WebSearchCallItem.svelte';
	export let data;

	let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	$: classId = parseInt($page.params.classId ?? '');
	$: threadId = parseInt($page.params.threadId ?? '');
	$: threadMgr = new ThreadManager(
		fetch,
		classId,
		threadId,
		data.threadData,
		data.threadInteractionMode || 'chat',
		userTimezone
	);
	$: isPrivate = data.class?.private || false;
	$: isAnonymousSession = data?.me?.status === 'anonymous';
	$: teachers = data?.supervisors || [];
	$: canDeleteThread = data.canDeleteThread;
	$: canPublishThread = data.canPublishThread;
	$: canViewAssistant = data.canViewAssistant;
	$: messages = threadMgr.messages;
	$: participants = threadMgr.participants;
	$: published = threadMgr.published;
	$: version = threadMgr.version;
	$: threadName = threadMgr.thread?.name || 'Thread';
	$: groupName = data.class?.name || `Group ${classId}`;
	$: threadLink = `${$page.url.origin}/group/${classId}/thread/${threadId}`;
	$: lectureVideoSrc = (() => {
		const base = api.fullPath(`/class/${classId}/thread/${threadId}/video`);
		const anonymousSessionToken = getAnonymousSessionToken();
		const anonymousShareToken = getAnonymousShareToken();
		const queryParts: string[] = [];
		if (anonymousSessionToken) {
			queryParts.push(`anonymous_session_token=${encodeURIComponent(anonymousSessionToken)}`);
		}
		if (anonymousShareToken) {
			queryParts.push(`anonymous_share_token=${encodeURIComponent(anonymousShareToken)}`);
		}
		const ltiSessionToken = api.getLTISessionToken();
		if (ltiSessionToken) {
			queryParts.push(`lti_session=${encodeURIComponent(ltiSessionToken)}`);
		}
		const queryString = queryParts.join('&');
		return queryParts.length > 0 ? `${base}?${queryString}` : base;
	})();
	$: error = threadMgr.error;
	$: threadManagerError = $error?.detail || null;
	$: assistantId = threadMgr.assistantId;
	$: isCurrentUser = $participants.user.includes('Me');
	$: threadInstructions = threadMgr.instructions;
	$: threadRecording = data.threadRecording;
	$: displayUserInfo = data.threadDisplayUserInfo;
	$: threadLectureVideoMismatch = data.threadLectureVideoMismatch === true;
	let lectureVideoRuntimeMismatch = false;
	let lectureVideoRuntimeAssistantMismatch = false;
	let lectureVideoElement: HTMLVideoElement | null = null;
	let lectureVideoAvailabilityCheckPending = false;
	let lectureVideoLastAvailabilityCheck = 0;
	let lectureVideoStateThreadId: number | null = null;
	$: {
		if (lectureVideoStateThreadId !== threadId) {
			lectureVideoStateThreadId = threadId;
			lectureVideoRuntimeMismatch = false;
			lectureVideoRuntimeAssistantMismatch = false;
			lectureVideoAvailabilityCheckPending = false;
			lectureVideoLastAvailabilityCheck = 0;
		}
	}
	$: effectiveLectureVideoMismatch = threadLectureVideoMismatch || lectureVideoRuntimeMismatch;
	$: effectiveLectureVideoAssistantMismatch =
		threadLectureVideoMismatch || lectureVideoRuntimeAssistantMismatch;
	let trashThreadFiles = writable<string[]>([]);
	let allFiles: Record<string, api.FileUploadInfo> = {};
	$: threadAttachments = threadMgr.attachments;
	$: allFiles = Object.fromEntries(
		Object.entries($threadAttachments)
			.filter(([k]) => !$trashThreadFiles.includes(k))
			.map(([k, v]) => [
				k,
				{
					state: 'success',
					progress: 100,
					file: { type: v.content_type, name: v.name },
					response: v,
					promise: Promise.resolve(v)
				} as api.FileUploadInfo
			])
	);
	$: fileSearchAcceptedFiles = supportsFileSearch
		? data.uploadInfo.fileTypes({
				file_search: true,
				code_interpreter: false,
				vision: false
			})
		: null;
	$: codeInterpreterAcceptedFiles = supportsCodeInterpreter
		? data.uploadInfo.fileTypes({
				file_search: false,
				code_interpreter: true,
				vision: false
			})
		: null;
	$: visionAcceptedFiles = supportsVision
		? data.uploadInfo.fileTypes({
				file_search: false,
				code_interpreter: false,
				vision: true
			})
		: null;
	$: fileSearchAttachmentCount = Object.entries($threadAttachments).filter(
		([k, v]) =>
			!$trashThreadFiles.includes(k) && (fileSearchAcceptedFiles ?? '').includes(v.content_type)
	).length;
	$: codeInterpreterAttachmentCount = Object.entries($threadAttachments).filter(
		([k, v]) =>
			!$trashThreadFiles.includes(k) &&
			(codeInterpreterAcceptedFiles ?? '').includes(v.content_type)
	).length;
	type ChatInputHandle = { addFiles: (selectedFiles: File[]) => void };
	let chatInputRef: ChatInputHandle | null = null;
	let dropOverlayVisible = false;
	let dropDragCounter = 0;

	let supportsVision = false;
	$: {
		const supportVisionModels = (
			data.modelInfo.filter((model: api.AssistantModelLite) => model.supports_vision) || []
		).map((model: api.AssistantModelLite) => model.id);
		supportsVision = supportVisionModels.includes(data.threadModel);
	}
	let visionSupportOverride: boolean | undefined;
	$: {
		visionSupportOverride =
			data.class?.ai_provider === 'azure'
				? data.modelInfo.find((model: api.AssistantModelLite) => model.id === data.threadModel)
						?.azure_supports_vision
				: undefined;
	}
	$: submitting = threadMgr.submitting;
	$: waiting = threadMgr.waiting;
	$: loading = threadMgr.loading;
	$: canFetchMore = threadMgr.canFetchMore;
	$: supportsFileSearch = data.availableTools.includes('file_search') || false;
	$: supportsCodeInterpreter = data.availableTools.includes('code_interpreter') || false;
	$: supportsWebSearch = data.availableTools.includes('web_search') || false;
	$: supportsMCPServer = data.availableTools.includes('mcp_server') || false;
	let supportsReasoning = false;
	$: {
		const model = data.modelInfo.find(
			(model: api.AssistantModelLite) => model.id === data.threadModel
		);
		supportsReasoning = model?.supports_reasoning || false;
	}
	// TODO - should figure this out by checking grants instead of participants
	$: canSubmit = !!$participants.user && $participants.user.includes('Me');
	$: assistantDeleted = !$assistantId && $assistantId === 0;
	let useLatex = false;
	let useImageDescriptions = false;
	let assistantVersion: number | null = null;
	let assistantInteractionMode: 'voice' | 'chat' | 'lecture_video' | null = null;
	let allowUserFileUploads = true;
	let allowUserImageUploads = true;
	$: chatVisionAcceptedFiles = allowUserImageUploads ? visionAcceptedFiles : null;
	$: chatFileSearchAcceptedFiles = allowUserFileUploads ? fileSearchAcceptedFiles : null;
	$: chatCodeInterpreterAcceptedFiles = allowUserFileUploads ? codeInterpreterAcceptedFiles : null;
	$: chatInputDisabled = !canSubmit || assistantDeleted || !!$navigating || !canViewAssistant;
	$: canDropUploadsIntoThread =
		data.threadInteractionMode === 'chat' &&
		assistantInteractionMode === 'chat' &&
		chatInputRef !== null &&
		!chatInputDisabled &&
		!($submitting || $waiting) &&
		!!(chatVisionAcceptedFiles || chatFileSearchAcceptedFiles || chatCodeInterpreterAcceptedFiles);
	let bypassedSettingsSections: {
		id: string;
		title: string;
		items: { label: string; hidden: boolean; description: string }[];
	}[] = [];
	$: {
		const assistant = data.assistants.find(
			(assistant: api.Assistant) => assistant.id === $assistantId
		);
		if (assistant) {
			useLatex = assistant.use_latex || false;
			useImageDescriptions = assistant.use_image_descriptions || false;
			assistantInteractionMode = assistant.interaction_mode;
			assistantVersion = assistant.version ?? null;
			allowUserFileUploads = assistant.allow_user_file_uploads ?? true;
			allowUserImageUploads = assistant.allow_user_image_uploads ?? true;
		} else {
			useLatex = false;
			useImageDescriptions = false;
			assistantInteractionMode = null;
			assistantVersion = null;
			allowUserFileUploads = true;
			allowUserImageUploads = true;
			if (data.threadData.anonymous_session) {
				console.warn(`Definition for assistant ${$assistantId} not found.`);
			}
		}
		const isSupervisor = data.isSupervisor === true;
		const nextBypassedSettingsSections: {
			id: string;
			title: string;
			items: { label: string; hidden: boolean; description: string }[];
		}[] = [];
		if (assistant && isSupervisor) {
			const hideFileSearchQueries = assistant.hide_file_search_queries === true;
			const hideFileSearchResultQuotes = assistant.hide_file_search_result_quotes === true;
			const hideFileSearchDocumentNames = assistant.hide_file_search_document_names === true;
			const hideWebSearchSources = assistant.hide_web_search_sources === true;
			const hideWebSearchActions = assistant.hide_web_search_actions === true;
			const hideReasoningSummaries = assistant.hide_reasoning_summaries === true;
			const hideMCPServerCallDetails = assistant.hide_mcp_server_call_details === true;

			if (supportsFileSearch) {
				nextBypassedSettingsSections.push({
					id: 'file-search',
					title: 'File Search',
					items: [
						{
							label: 'Queries',
							hidden: hideFileSearchQueries,
							description: hideFileSearchQueries
								? 'Members cannot see the queries the assistant uses to find relevant documents.'
								: 'Members can see the queries the assistant uses to find relevant documents.'
						},
						{
							label: 'Document Quotes',
							hidden: hideFileSearchResultQuotes,
							description: hideFileSearchResultQuotes
								? 'Members cannot see the document quotes the assistant retrieves from each file.'
								: 'Members can see the document quotes the assistant retrieves from each file.'
						},
						{
							label: 'Document Names',
							hidden: hideFileSearchDocumentNames,
							description: hideFileSearchDocumentNames
								? 'Members cannot see the names of the documents the assistant retrieves.'
								: 'Members can see the names of the documents the assistant retrieves.'
						}
					]
				});
			}
			if (supportsWebSearch) {
				nextBypassedSettingsSections.push({
					id: 'web-search',
					title: 'Web Search',
					items: [
						{
							label: 'Sources Considered',
							hidden: hideWebSearchSources,
							description: hideWebSearchSources
								? 'Members can only see web sources cited in the assistant responses, not the full list of web sources the assistant considered.'
								: 'Members can see the full list of web sources the assistant considered.'
						},
						{
							label: 'Search Actions',
							hidden: hideWebSearchActions,
							description: hideWebSearchActions
								? 'Members can see that the assistant is searching the web without revealing specific details.'
								: 'Members can see the specific web search actions such as queries, clicks, and extraction.'
						}
					]
				});
			}
			if (supportsReasoning) {
				nextBypassedSettingsSections.push({
					id: 'reasoning',
					title: 'Reasoning',
					items: [
						{
							label: 'Reasoning Summaries',
							hidden: hideReasoningSummaries,
							description: hideReasoningSummaries
								? 'Members cannot see summaries of the assistant reasoning process.'
								: 'Members can see summaries of the assistant reasoning process.'
						}
					]
				});
			}
			if (supportsMCPServer) {
				nextBypassedSettingsSections.push({
					id: 'mcp-server',
					title: 'MCP Server',
					items: [
						{
							label: 'MCP Call Details',
							hidden: hideMCPServerCallDetails,
							description: hideMCPServerCallDetails
								? 'Members see when the assistant makes calls to an MCP Server, but not detailed payloads or responses.'
								: 'Members can see detailed payloads and responses from MCP Server calls.'
						}
					]
				});
			}
		}
		bypassedSettingsSections = nextBypassedSettingsSections;
	}
	$: statusComponents = (data.statusComponents || {}) as Partial<
		Record<string, api.StatusComponentUpdate[]>
	>;
	let latestIncidentUpdateTimestamps: Record<string, number> = {};
	$: latestIncidentUpdateTimestamps = computeLatestIncidentTimestamps(statusComponents);
	$: resolvedAssistantVersion = Number(assistantVersion ?? $version ?? 0);
	$: statusComponentId =
		$version >= 3 ? api.STATUS_COMPONENT_IDS.nextGen : api.STATUS_COMPONENT_IDS.classic;
	$: assistantStatusUpdates = filterLatestIncidentUpdates(
		statusComponents[statusComponentId],
		latestIncidentUpdateTimestamps
	);
	let showModerators = false;
	let showAssistantPrompt = false;
	let settingsOpen = false;
	let printingThread = false;
	let messagesContainer: HTMLDivElement | null = null;

	function isFileCitation(a: api.TextAnnotation): a is api.TextAnnotationFileCitation {
		return a.type === 'file_citation' && a.text === 'responses_v3';
	}
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

	let currentMessageAttachments: api.ServerFile[] = [];
	// Get the name of the participant in the chat thread.
	const getName = (message: api.OpenAIMessage) => {
		if (message.role === 'user') {
			if (message?.metadata?.is_current_user) {
				return data?.me?.user?.name || data?.me?.user?.email || 'Me';
			}
			return (message?.metadata?.name as string | undefined) || 'Anonymous User';
		} else {
			// Note that we need to distinguish between unknown and deleted assistants.
			if ($assistantId !== null) {
				return $participants.assistant[$assistantId] || 'PingPong Bot';
			}
			return 'PingPong Bot';
		}
	};

	export function processString(dirty_string: string): {
		clean_string: string;
		images: api.ImageProxy[];
	} {
		const jsonPattern = /\{"Rd1IFKf5dl"\s*:\s*\[.*?\]\}/s;
		const match = dirty_string.match(jsonPattern);

		let clean_string = dirty_string;
		let images: api.ImageProxy[] = [];

		if (match) {
			try {
				const user_images = JSON.parse(match[0]);
				images = user_images['Rd1IFKf5dl'] || [];
				clean_string = dirty_string.replace(jsonPattern, '').trim();
			} catch (error) {
				console.error('Failed to parse user images JSON:', error);
			}
		}

		return { clean_string, images };
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

	// Get the avatar URL of the participant in the chat thread.
	const getImage = (message: api.OpenAIMessage) => {
		if (message.role === 'user') {
			if (message?.metadata?.is_current_user) {
				return data?.me?.profile?.image_url || '';
			}
			return '';
		}
		// TODO - custom image for the assistant

		return '';
	};

	// Scroll to the bottom of the chat thread.
	const scroll = (el: HTMLDivElement, params: { messages: Message[]; threadId: number }) => {
		let lastScrollTop = el.scrollTop;
		let userPausedAutoScroll = false;
		let isProgrammaticScroll = false;
		let lastMessageId: string | null = params.messages[params.messages.length - 1]?.data.id ?? null;
		let currentThreadId = params.threadId;

		const scrollToBottom = () => {
			isProgrammaticScroll = true;
			el.scrollTo({
				top: el.scrollHeight,
				behavior: 'smooth'
			});
			requestAnimationFrame(() => {
				lastScrollTop = el.scrollTop;
				isProgrammaticScroll = false;
			});
		};

		const onScroll = () => {
			if (isProgrammaticScroll) {
				lastScrollTop = el.scrollTop;
				return;
			}
			const isScrollingDown = el.scrollTop > lastScrollTop;
			const isScrollingUp = el.scrollTop < lastScrollTop - 5;
			const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;

			// Pause auto-scroll on upward scroll
			if (isScrollingUp) {
				userPausedAutoScroll = true;
			}
			// Resume auto-scroll only when scrolling down and near the bottom
			if (userPausedAutoScroll && isScrollingDown && distanceFromBottom < 50) {
				userPausedAutoScroll = false;
			}
			lastScrollTop = el.scrollTop;
		};

		el.addEventListener('scroll', onScroll, { passive: true });
		scrollToBottom();

		return {
			update: (nextParams: { messages: Message[]; threadId: number }) => {
				// Reset scroll state when navigating to a different thread
				if (nextParams.threadId !== currentThreadId) {
					currentThreadId = nextParams.threadId;
					userPausedAutoScroll = false;
					lastMessageId = null;
					lastScrollTop = 0;
					scrollToBottom();
					return;
				}

				const nextMessages = nextParams.messages;
				const nextLastMessage = nextMessages[nextMessages.length - 1];
				const nextLastMessageId = nextLastMessage?.data.id ?? null;
				const hasNewTailMessage = nextLastMessageId && nextLastMessageId !== lastMessageId;
				const isCurrentUserTail =
					nextLastMessage?.data.role === 'user' &&
					nextLastMessage?.data.metadata?.is_current_user === true;
				lastMessageId = nextLastMessageId;
				requestAnimationFrame(() => {
					// Force scroll when user sends a new message
					if (hasNewTailMessage && isCurrentUserTail) {
						userPausedAutoScroll = false;
					}
					if (!userPausedAutoScroll) {
						scrollToBottom();
					}
				});
			},
			destroy: () => {
				el.removeEventListener('scroll', onScroll);
			}
		};
	};

	// Fetch an earlier page of messages
	const fetchMoreMessages = async () => {
		await threadMgr.fetchMore();
	};

	// Fetch the entire thread so the print view includes every message/tool call.
	const loadEntireThreadForPrint = async () => {
		while (get(canFetchMore)) {
			await fetchMoreMessages();
			await tick();
		}
	};

	// Fetch a singular code interpreter step result
	const fetchCodeInterpreterResult = async (content: api.Content) => {
		if (content.type !== 'code_interpreter_call_placeholder') {
			sadToast('Invalid code interpreter request.');
			return;
		}
		try {
			await threadMgr.fetchCodeInterpreterResult(content.run_id, content.step_id);
		} catch (e) {
			sadToast(
				`Failed to load code interpreter results. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
			);
		}
	};

	// Handle sending a message
	const postMessage = async ({
		message,
		code_interpreter_file_ids,
		file_search_file_ids,
		vision_file_ids,
		visionFileImageDescriptions,
		callback
	}: ChatInputMessage) => {
		try {
			await threadMgr.postMessage(
				data.me.user!.id,
				message,
				callback,
				code_interpreter_file_ids,
				file_search_file_ids,
				vision_file_ids,
				visionFileImageDescriptions,
				currentMessageAttachments
			);
		} catch (e) {
			callback({
				success: false,
				errorMessage: `Failed to send message. Error: ${errorMessage(e, "Something went wrong while sending your message. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.")}`,
				message_sent: false
			});
		}
	};

	// Handle submit on the chat input
	const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
		await postMessage(e.detail);
	};

	// Handle file upload
	const handleUpload = (
		f: File,
		onProgress: (p: number) => void,
		purpose: api.FileUploadPurpose = 'assistants',
		useImageDescriptions: boolean = false
	) => {
		return api.uploadUserFile(
			data.class.id,
			data.me.user!.id,
			f,
			{ onProgress },
			purpose,
			useImageDescriptions
		);
	};

	// Handle file removal
	const handleRemove = async (fileId: number) => {
		const result = await api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId);
		if (result.$status >= 300) {
			sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
			throw new Error(result.detail || 'unknown error');
		}
	};

	const handleDismissError = () => {
		threadMgr.dismissError();
	};

	const isFileDrag = (event: DragEvent) =>
		Array.from(event.dataTransfer?.types ?? []).includes('Files');

	const resetDropOverlay = () => {
		dropOverlayVisible = false;
		dropDragCounter = 0;
	};

	const handleThreadDragEnter = (event: DragEvent) => {
		if (!canDropUploadsIntoThread || !isFileDrag(event)) {
			return;
		}
		event.preventDefault();
		event.stopPropagation();
		dropDragCounter += 1;
		dropOverlayVisible = true;
	};

	const handleThreadDragOver = (event: DragEvent) => {
		if (!canDropUploadsIntoThread || !isFileDrag(event)) {
			return;
		}
		event.preventDefault();
		event.stopPropagation();
		if (event.dataTransfer) {
			event.dataTransfer.dropEffect = 'copy';
		}
		dropOverlayVisible = true;
	};

	const handleThreadDragLeave = (event: DragEvent) => {
		if (!canDropUploadsIntoThread || !dropOverlayVisible) {
			return;
		}
		event.preventDefault();
		event.stopPropagation();
		dropDragCounter = Math.max(0, dropDragCounter - 1);
		if (dropDragCounter === 0) {
			dropOverlayVisible = false;
		}
	};

	const handleThreadDrop = (event: DragEvent) => {
		if (!canDropUploadsIntoThread || !isFileDrag(event)) {
			return;
		}
		event.preventDefault();
		event.stopPropagation();
		const droppedFiles = Array.from(event.dataTransfer?.files ?? []);
		resetDropOverlay();
		if (!droppedFiles.length) {
			return;
		}
		chatInputRef?.addFiles(droppedFiles);
	};

	const startNewChat = async () => {
		if (isAnonymousSession) {
			if (hasAnonymousShareToken()) {
				resetAnonymousSessionToken();
				await goto(
					resolve(
						`/group/${classId}/shared/assistant/${$assistantId}?share_token=${getAnonymousShareToken()}`
					)
				);
			} else {
				sadToast('Cannot start a new chat in this anonymous session.');
			}
		} else {
			await goto(resolve(`/group/${classId}?assistant=${$assistantId}`));
		}
	};

	// Fallback link copy handling for environments (e.g., iframes) where Clipboard API is blocked
	let copyLinkModalOpen = false;
	let shareLink = '';
	let shareLinkInputEl: HTMLInputElement | null = null;

	type PermissionsPolicyLike = {
		allows?: (feature: string, origin?: string) => boolean;
		allowsFeature?: (feature: string) => boolean;
	};

	const canProgrammaticallyCopy = () => {
		try {
			// Check Permissions Policy if available to avoid triggering violations in iframes
			const d = document as unknown as {
				permissionsPolicy?: PermissionsPolicyLike;
				featurePolicy?: PermissionsPolicyLike;
			};
			const pol: PermissionsPolicyLike | undefined = d.permissionsPolicy ?? d.featurePolicy;
			if (pol) {
				if (typeof pol.allows === 'function' && !pol.allows('clipboard-write')) return false;
				if (typeof pol.allowsFeature === 'function' && !pol.allowsFeature('clipboard-write'))
					return false;
			}
			return !!navigator.clipboard && window.isSecureContext;
		} catch {
			return false;
		}
	};

	const openManualCopyModal = async (url: string) => {
		shareLink = url;
		copyLinkModalOpen = true;
		await tick();
		// Focus and select for quick manual copy (Cmd/Ctrl+C)
		shareLinkInputEl?.focus();
		shareLinkInputEl?.select();
	};

	const handleCopyLinkClick = async (e?: Event) => {
		e?.preventDefault?.();
		e?.stopPropagation?.();
		const url = `${$page.url.origin}/group/${classId}/thread/${threadId}`;
		if (canProgrammaticallyCopy()) {
			try {
				await navigator.clipboard.writeText(url);
				happyToast('Link copied to clipboard', 3000);
				return;
			} catch {
				// Fall through to manual copy
			}
		}
		// Manual copy fallback without using Clipboard API (avoids permissions policy violations)
		await openManualCopyModal(url);
	};

	/**
	 * Publish or unpublish a thread.
	 */
	const togglePublish = async () => {
		if (!threadMgr.thread) {
			return;
		}
		let verb = 'publish';
		try {
			if (threadMgr.thread.private) {
				await threadMgr.publish();
			} else {
				verb = 'unpublish';
				await threadMgr.unpublish();
			}
			invalidateAll();
		} catch (e) {
			sadToast(
				`Failed to ${verb} thread. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
			);
		}
	};

	const handlePrintThread = async () => {
		if (printingThread) {
			return;
		}
		printingThread = true;
		try {
			await loadEntireThreadForPrint();
			await tick();

			if (typeof window === 'undefined') {
				return;
			}

			if (!messagesContainer) {
				sadToast('Unable to find the thread content to print.');
				return;
			}

			// Wait for images to load before printing
			const images = Array.from(messagesContainer.querySelectorAll('img'));
			await Promise.all(
				images.map(
					(img) =>
						new Promise<void>((resolve) => {
							if (img.complete) {
								resolve();
								return;
							}
							const done = () => {
								img.removeEventListener('load', done);
								img.removeEventListener('error', done);
								resolve();
							};
							img.addEventListener('load', done);
							img.addEventListener('error', done);
						})
				)
			);

			window.print();
		} catch (e) {
			console.error('Failed to print thread', e);
			sadToast(
				`Unable to print this thread. Error: ${errorMessage(e, 'Please try again in a moment.')}`
			);
		} finally {
			settingsOpen = false;
			printingThread = false;
		}
	};

	let confirmNavigation = true;
	/**
	 * Delete the thread.
	 */
	const deleteThread = async () => {
		if (!threadMgr.thread) {
			return;
		}
		try {
			if (!confirm('Are you sure you want to delete this thread? This cannot be undone!')) {
				return;
			}
			await threadMgr.delete();
			happyToast('Thread deleted.');
			confirmNavigation = false;
			if (isAnonymousSession) {
				if (hasAnonymousShareToken()) {
					resetAnonymousSessionToken();
					await goto(
						resolve(
							`/group/${classId}/shared/assistant/${$assistantId}?share_token=${getAnonymousShareToken()}`
						)
					);
				} else {
					await goto(resolve(`/`), { invalidateAll: true });
				}
			} else {
				await goto(resolve(`/group/${classId}`), { invalidateAll: true });
			}
		} catch (e) {
			sadToast(
				`Failed to delete thread. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
			);
		}
	};

	let wavRecorder: WavRecorder | null = null;
	let wavStreamPlayer: WavStreamPlayer | null = null;
	let microphoneAccess = false;
	let audioDevices: ExtendedMediaDeviceInfo[] = [];
	let selectedAudioDevice: ExtendedMediaDeviceInfo | null = null;
	let openMicrophoneModal = false;

	/**
	 * Select an audio device. If no device ID is provided, the first available device will be selected.
	 * @param deviceId Optional ID of the audio device to select.
	 */
	const selectAudioDevice = (deviceId?: string) => {
		const lookupDeviceId = deviceId || selectedAudioDevice?.deviceId;
		if (lookupDeviceId) {
			selectedAudioDevice =
				audioDevices.find((device) => device.deviceId === lookupDeviceId) || null;
		}

		// Only fall back to default device if no device was explicitly selected
		if (!selectedAudioDevice && audioDevices.length > 0) {
			const defaultDevice = audioDevices.find((device) => device.default);
			if (defaultDevice) {
				selectedAudioDevice = defaultDevice;
			}
		}

		// If no device is selected, select the first available device
		if (!selectedAudioDevice) {
			selectedAudioDevice = audioDevices[0] || null;
		}
	};

	/**
	 * Handle changes in the list of available audio devices.
	 * This function updates the list of audio devices and selects a default device.
	 * @param devices The updated list of available audio devices.
	 */
	const handleDeviceChange = (devices: ExtendedMediaDeviceInfo[]) => {
		audioDevices = devices;
		selectAudioDevice();
	};

	/**
	 * Handle the setup of a session.
	 * This function initializes the WavRecorder and updates available audio devices.
	 * The user will be asked to allow microphone access.
	 */
	const handleSessionSetup = async () => {
		wavRecorder = new WavRecorder({ sampleRate: 24000, debug: true });
		wavStreamPlayer = new WavStreamPlayer({
			sampleRate: 24000,
			onAudioPartStarted: onAudioPartStartedProcessor
		});
		try {
			await wavStreamPlayer.connect();
		} catch (error) {
			if (error instanceof Error && error.message === AUDIO_WORKLET_UNSUPPORTED_MESSAGE) {
				sadToast(
					'Voice mode is unavailable in this browser or LMS iframe. Please use the latest Chrome, Edge, or Safari.'
				);
			} else {
				sadToast(
					`Failed to set up audio output to your speakers. Error: ${errorMessage(error, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
				);
			}
			wavRecorder.quit();
			wavRecorder = null;
			wavStreamPlayer = null;
			return;
		}
		try {
			audioDevices = await wavRecorder.listDevices();
			wavRecorder.listenForDeviceChange(handleDeviceChange);
			microphoneAccess = true;
		} catch (error) {
			sadToast(
				`Failed to access microphone. Error: ${errorMessage(error, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
			);
			wavRecorder.quit();
			wavRecorder = null;
			wavStreamPlayer = null;
			return;
		}

		// handleDeviceChange is called when set
		// when listenForDeviceChange is called,
		// but just in case
		if (!selectedAudioDevice) {
			selectAudioDevice();
		}
	};

	let socket: WebSocket | null = null;
	let startingAudioSession = false;
	let audioSessionStarted = false;

	/**
	 * Process audio chunks.
	 * This function sends the audio data to the server via WebSocket.
	 * @param data The audio data to be processed.
	 * @param data.raw The raw audio data.
	 * @param data.mono The mono audio data.
	 */
	const chunkProcessor = (data: { raw: ArrayBuffer; mono: ArrayBuffer }) => {
		if (!socket || !audioSessionStarted) {
			return;
		}
		const audio = new Uint8Array(data.mono);
		const buffer = new ArrayBuffer(8 + audio.length);
		const view = new DataView(buffer);
		view.setFloat64(0, Date.now());
		new Uint8Array(buffer, 8).set(audio);
		socket.send(buffer);
	};

	/**
	 * Handle the beginning of a new assistant message playback.
	 * @param data The data associated with the new message.
	 * @param data.trackId The ID of the track.
	 * @param data.timestamp The timestamp of when the message started.
	 */
	const onAudioPartStartedProcessor = (data: {
		trackId: string;
		eventId: string;
		timestamp: number;
	}) => {
		socket?.send(
			JSON.stringify({
				type: 'response.audio.delta.started',
				item_id: data.trackId,
				event_id: data.eventId,
				started_playing_at: data.timestamp
			})
		);
	};

	/**
	 * Reset the audio session.
	 * This function closes the WebSocket connection and resets the state of the audio session.
	 */
	const resetAudioSession = async () => {
		if (socket) {
			socket.close();
			socket = null;
		}
		startingAudioSession = false;
		audioSessionStarted = false;
		openMicrophoneModal = false;
		microphoneAccess = false;
		audioDevices = [];
		selectedAudioDevice = null;
		if (wavRecorder) {
			await wavRecorder.quit();
			wavRecorder = null;
		}
		if (wavStreamPlayer) {
			await wavStreamPlayer.interrupt();
			wavStreamPlayer = null;
		}
	};

	/**
	 * Handle the start of a session.
	 */
	const handleSessionStart = async () => {
		if (startingAudioSession) {
			return;
		}
		startingAudioSession = true;
		if (!wavRecorder) {
			sadToast('We failed to start the session. Please try again.');
			return;
		}
		if (!selectedAudioDevice) {
			sadToast('No audio device selected. Please select a microphone.');
			return;
		}
		if (!wavStreamPlayer) {
			sadToast('Failed to set up audio output to your speakers.');
			return;
		}

		socket = api.createAudioWebsocket(classId, threadId);
		socket.binaryType = 'arraybuffer';

		socket.addEventListener('message', async (event) => {
			const message = JSON.parse(event.data);
			switch (message.type) {
				case 'session.updated':
					if (!wavRecorder) {
						sadToast('We failed to start the session. Please try again.');
						return;
					}
					if (!selectedAudioDevice) {
						sadToast('No audio device selected. Please select a microphone.');
						return;
					}
					try {
						await wavRecorder.begin(selectedAudioDevice.deviceId);
					} catch (error) {
						if (error instanceof Error && error.message === AUDIO_WORKLET_UNSUPPORTED_MESSAGE) {
							sadToast(
								'Voice mode is unavailable in this browser or LMS iframe. Please use the latest Chrome, Edge, or Safari.'
							);
						} else {
							sadToast(
								`Failed to start recording. Error: ${errorMessage(error, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
							);
						}
						await resetAudioSession();
						return;
					}
					await wavRecorder.record(chunkProcessor);
					startingAudioSession = false;
					audioSessionStarted = true;
					break;
				case 'input_audio_buffer.speech_started': {
					if (!wavStreamPlayer) {
						sadToast('Failed to set up audio output to your speakers.');
						return;
					}
					await wavStreamPlayer.interrupt();
					const trackSampleOffset = await wavStreamPlayer.interrupt();
					if (trackSampleOffset?.trackId) {
						const { trackId, offset } = trackSampleOffset;
						if (!socket) {
							sadToast('Error connecting with the server.');
							return;
						}
						if (!wavRecorder) {
							sadToast('Failed to set up audio output to your speakers.');
							return;
						}
						socket.send(
							JSON.stringify({
								type: 'conversation.item.truncate',
								item_id: trackId,
								audio_end_ms: Math.floor((offset / wavStreamPlayer.getSampleRate()) * 1000)
							})
						);
					}
					break;
				}
				case 'response.audio.delta':
					if (!wavStreamPlayer) {
						sadToast('Failed to set up audio output to your speakers.');
						return;
					}
					wavStreamPlayer.add16BitPCM(
						base64ToArrayBuffer(message.audio),
						message.item_id,
						message.event_id
					);
					break;
				case 'error':
					if (message.error.type === 'invalid_request_error') {
						sadToast(
							`Failed to start session. Error: ${errorMessage(message.error.message, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
						);
						await resetAudioSession();
					} else {
						sadToast(
							`We faced an error. Error: ${errorMessage(
								message.error.message,
								"We're facing an unknown error. Check PingPong's status page for updates if this persists."
							)}`
						);
					}
					break;
				default:
					console.warn('Unknown message type:', message.type);
			}
		});
	};

	let endingAudioSession = false;
	/**
	 * Handle session end.
	 */
	const handleSessionEnd = async () => {
		if (endingAudioSession) {
			return;
		}
		endingAudioSession = true;
		if (socket) {
			socket.close();
			socket = null;
		}
		audioDevices = [];
		selectedAudioDevice = null;
		if (wavRecorder) {
			await wavRecorder.quit();
			wavRecorder = null;
		}
		if (wavStreamPlayer) {
			await wavStreamPlayer.interrupt();
			wavStreamPlayer = null;
		}
		await invalidateAll();
		startingAudioSession = false;
		audioSessionStarted = false;
		openMicrophoneModal = false;
		microphoneAccess = false;
		endingAudioSession = false;
	};

	/*
	 * Delete a file from the thread.
	 */
	const setFileState = (fileId: string, state: api.FileUploadInfo['state']) => {
		const existing = allFiles[fileId];
		if (!existing) return;
		allFiles = {
			...allFiles,
			[fileId]: { ...existing, state }
		};
	};

	const removeFile = async (evt: CustomEvent<api.FileUploadInfo>) => {
		const file = evt.detail;
		if (file.state === 'deleting' || !(file.response && 'file_id' in file.response)) {
			return;
		} else {
			setFileState((file.response as api.ServerFile).file_id, 'deleting');
			const result = await api.deleteThreadFile(
				fetch,
				data.class.id,
				threadId,
				(file.response as api.ServerFile).file_id
			);
			if (result.$status >= 300) {
				setFileState((file.response as api.ServerFile).file_id, 'success');
				sadToast(`Failed to delete file: ${result.detail || 'unknown error'}`);
			} else {
				trashThreadFiles.update((files) => [...files, (file.response as api.ServerFile).file_id]);
				happyToast('Thread file successfully deleted.');
			}
		}
	};

	const showModeratorsModal = () => {
		showModerators = true;
	};

	let showPlayer = false;
	let audioUrl: string | null = null;
	const fetchRecording = async () => {
		const res = await api.getThreadRecording(fetch, classId, threadId);
		const chunks: Uint8Array[] = [];

		for await (const chunk of await res) {
			if ((chunk as { type: string }).type === 'error') {
				sadToast(`Failed to load recording: ${(chunk as { detail: string }).detail}`);
				return;
			}
			chunks.push(chunk as Uint8Array);
		}

		const blob = new Blob(chunks as BlobPart[], { type: 'audio/webm' });
		audioUrl = URL.createObjectURL(blob);
		showPlayer = true;
	};

	let transcribingRecording = false;
	const transcribeRecording = async () => {
		if (transcribingRecording) {
			return;
		}
		transcribingRecording = true;
		settingsOpen = false;
		try {
			const res = await api.transcribeThreadRecording(fetch, classId, threadId);
			if (res.$status >= 300) {
				sadToast(`Failed to request transcription: ${res.detail || 'unknown error'}`);
				return;
			}
			happyToast(
				"We've started transcribing your recording. You'll receive an email when it's done.",
				4000
			);
		} catch (e) {
			sadToast(
				`Failed to request transcription. Error: ${errorMessage(e, "We're facing an unknown error. Check PingPong's status page for updates if this persists.")}`
			);
		} finally {
			transcribingRecording = false;
		}
	};

	const logLectureVideoEvent = (eventName: string, details?: Record<string, unknown>) => {
		const mediaError = lectureVideoElement?.error;
		const mediaState = lectureVideoElement
			? {
					readyState: lectureVideoElement.readyState,
					networkState: lectureVideoElement.networkState,
					currentTime: lectureVideoElement.currentTime,
					paused: lectureVideoElement.paused,
					errorCode: mediaError?.code ?? null,
					errorMessage: mediaError?.message ?? null
				}
			: null;

		console.info('[lecture-video]', eventName, {
			threadId,
			classId,
			src: lectureVideoSrc,
			timestamp: new Date().toISOString(),
			...mediaState,
			...details
		});
	};

	const markLectureVideoUnavailable = (reason: 'generic' | 'assistant_mismatch') => {
		if (effectiveLectureVideoMismatch) {
			logLectureVideoEvent('mark-unavailable:skipped', {
				reason: 'already-mismatch',
				unavailableReason: reason
			});
			return;
		}

		logLectureVideoEvent('mark-unavailable:start', { unavailableReason: reason });

		// Detach the source immediately so the browser stops retrying failed segment requests.
		if (lectureVideoElement) {
			lectureVideoElement.pause();
			lectureVideoElement.removeAttribute('src');
			lectureVideoElement.load();
		}

		// Stop retries by unmounting the video player immediately.
		lectureVideoRuntimeAssistantMismatch = reason === 'assistant_mismatch';
		lectureVideoRuntimeMismatch = true;
		logLectureVideoEvent('mark-unavailable:done', { unavailableReason: reason });
	};

	const checkLectureVideoAvailability = async () => {
		if (
			effectiveLectureVideoMismatch ||
			lectureVideoAvailabilityCheckPending ||
			Date.now() - lectureVideoLastAvailabilityCheck < 2000
		) {
			logLectureVideoEvent('availability-check:skipped', {
				effectiveLectureVideoMismatch,
				lectureVideoAvailabilityCheckPending,
				withinThrottleWindow: Date.now() - lectureVideoLastAvailabilityCheck < 2000
			});
			return;
		}

		lectureVideoAvailabilityCheckPending = true;
		lectureVideoLastAvailabilityCheck = Date.now();
		logLectureVideoEvent('availability-check:start');
		try {
			const response = await fetch(lectureVideoSrc, {
				headers: { Range: 'bytes=0-0' }
			});
			logLectureVideoEvent('availability-check:response', {
				status: response.status,
				ok: response.ok
			});
			if (response.status !== 200 && response.status !== 206) {
				const isAssistantMismatch = response.status === 409;
				markLectureVideoUnavailable(isAssistantMismatch ? 'assistant_mismatch' : 'generic');
			}
		} catch (e) {
			logLectureVideoEvent('availability-check:error', {
				error: errorMessage(e, 'unknown error')
			});
			markLectureVideoUnavailable('generic');
		} finally {
			lectureVideoAvailabilityCheckPending = false;
			logLectureVideoEvent('availability-check:done');
		}
	};

	const handleLectureVideoError = () => {
		logLectureVideoEvent('video:error');
		markLectureVideoUnavailable('generic');
	};

	const handleLectureVideoBuffering = () => {
		logLectureVideoEvent('video:buffering');
		void checkLectureVideoAvailability();
	};

	const handleLectureVideoLifecycle = (name: string) => {
		logLectureVideoEvent(`video:${name}`);
	};

	afterNavigate(async () => {
		await resetAudioSession();
	});

	beforeNavigate((nav) => {
		if (
			(data.isSharedAssistantPage || data.isSharedThreadPage) &&
			isAnonymousSession &&
			confirmNavigation
		) {
			if (
				!confirm(
					`${data.me.status === 'anonymous' ? 'You will lose access to this thread.' : "You won't be able to edit this thread."}\n\nAre you sure you want to leave this page?`
				)
			) {
				nav.cancel();
				return;
			}
		}
	});
</script>

<svelte:window on:dragend={resetDropOverlay} on:drop={resetDropOverlay} />

<div
	class="relative flex min-h-0 w-full grow flex-col justify-between"
	role="region"
	aria-label="Thread detail"
	ondragenter={handleThreadDragEnter}
	ondragover={handleThreadDragOver}
	ondragleave={handleThreadDragLeave}
	ondrop={handleThreadDrop}
>
	{#if data.threadInteractionMode === 'lecture_video'}
		<div class="flex h-full w-full flex-col items-center justify-center">
			{#if effectiveLectureVideoMismatch}
				<div class="flex h-full w-full items-center justify-center p-4">
					<div
						class="w-full max-w-2xl rounded-lg border border-amber-300 bg-amber-50 px-5 py-4 text-amber-900"
					>
						{#if effectiveLectureVideoAssistantMismatch}
							This lecture video is no longer available for this thread because the assistant
							configuration changed. Please start a new lecture thread.
						{:else}
							This lecture video could not be loaded. Please check your connection and try
							refreshing the page.
						{/if}
					</div>
				</div>
			{:else}
				<div class="flex h-full w-full flex-col items-center justify-center rounded-lg p-4">
					<div class="mb-2 flex items-center gap-2">
						<DropdownBadge
							extraClasses="border-red-400 from-red-100 to-red-200 px-2 py-0.5 text-base text-red-800"
							><span slot="name">In Development</span></DropdownBadge
						>
						<QuestionCircleOutline
							id="lecture-video-dev-tooltip-detail"
							class="h-5 w-5 cursor-help text-gray-600"
						/>
						<Tooltip
							triggeredBy="#lecture-video-dev-tooltip-detail"
							class="font-light"
							arrow={false}
							>Lecture Video mode is in active development and not fully functional.</Tooltip
						>
					</div>

					<!-- svelte-ignore a11y_media_has_caption -->
					<video
						class="h-auto max-h-full w-full max-w-6xl rounded-lg shadow-lg"
						bind:this={lectureVideoElement}
						controls
						playsinline
						preload="metadata"
						src={lectureVideoSrc}
						onerror={handleLectureVideoError}
						onstalled={handleLectureVideoBuffering}
						onwaiting={handleLectureVideoBuffering}
						onloadstart={() => handleLectureVideoLifecycle('loadstart')}
						onloadedmetadata={() => handleLectureVideoLifecycle('loadedmetadata')}
						oncanplay={() => handleLectureVideoLifecycle('canplay')}
						onplaying={() => handleLectureVideoLifecycle('playing')}
						onpause={() => handleLectureVideoLifecycle('pause')}
						onprogress={() => handleLectureVideoLifecycle('progress')}
						onseeking={() => handleLectureVideoLifecycle('seeking')}
						onseeked={() => handleLectureVideoLifecycle('seeked')}
						onended={() => handleLectureVideoLifecycle('ended')}
					>
						Your browser does not support HTML5 video.
					</video>
				</div>
			{/if}
		</div>
	{:else}
		<div
			class={`messages-container overflow-y-auto px-2 pb-4 lg:px-4 ${
				data.isSharedAssistantPage || data.isSharedThreadPage ? 'pt-10' : ''
			}`}
			bind:this={messagesContainer}
			use:scroll={{ messages: $messages, threadId }}
		>
			<div class="print-only print-header">
				<div class="print-header__brand">
					<Logo size={9} />
					<div class="print-header__brand-text">PingPong</div>
				</div>
				<div class="print-header__meta">
					<div><span class="label">Group</span><span>{groupName}</span></div>
					<div><span class="label">Thread</span><span>{threadName}</span></div>
				</div>
				<div class="print-header__link">{threadLink}</div>
			</div>
			{#if $canFetchMore}
				<div class="flex grow justify-center">
					<Button size="sm" class="text-sky-600 hover:text-sky-800" onclick={fetchMoreMessages}>
						<RefreshOutline class="me-2 h-3 w-3" /> Load earlier messages ...
					</Button>
				</div>
			{/if}
			{#each $messages as message (message.data.id)}
				{@const attachment_file_ids = message.data.attachments
					? new Set(message.data.attachments.map((attachment) => attachment.file_id))
					: new Set([])}
				<div class="flex gap-x-3 px-6 py-4">
					<div class="shrink-0">
						{#if message.data.role === 'user'}
							<Avatar size="sm" src={getImage(message.data)} />
						{:else}
							<Logo size={8} />
						{/if}
					</div>
					<div class="w-full max-w-full">
						<div
							class="mt-1 mb-2 flex flex-wrap items-center gap-2 font-semibold text-blue-dark-40"
						>
							<span class="flex items-center gap-2">
								{getName(message.data)}
								{#if message.data.role !== 'user' && !assistantDeleted}
									<AssistantVersionBadge version={$version} extraClasses="shrink-0" />
								{/if}
							</span>
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
												<MCPServerCallItem
													content={item}
													forceOpen={printingThread}
													showServerLabel={false}
													compact={true}
												/>
											{:else if item.type === 'mcp_list_tools_call'}
												<MCPListToolsCallItem
													content={item}
													forceOpen={printingThread}
													showServerLabel={false}
													compact={true}
												/>
											{/if}
										{/each}
									</div>
								</div>
							{:else}
								{@const content = block.content}
								{#if content.type === 'text'}
									{@const { clean_string, images } = processString(content.text.value)}
									{@const imageInfo = convertImageProxyToInfo(images)}
									{@const quoteCitations = (content.text.annotations ?? []).filter(isFileCitation)}
									{@const parsedTextContent = parseTextContent(
										{ value: clean_string, annotations: content.text.annotations },
										$version,
										api.fullPath(`/class/${classId}/thread/${threadId}`)
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
									{#if attachment_file_ids.size > 0}
										<div class="flex flex-wrap gap-2">
											{#each imageInfo as image (image.response && 'file_id' in image.response ? image.response.file_id : image.file.name)}
												{#if !(image.response && 'file_id' in image.response && image.response.file_id in allFiles)}
													<FilePlaceholder
														info={image}
														purpose="vision"
														mimeType={data.uploadInfo.mimeType}
														preventDeletion={true}
														on:delete={() => {}}
													/>
												{/if}
											{/each}
										</div>
									{/if}
								{:else if content.type === 'code'}
									{#if printingThread}
										<div class="w-full leading-6">
											<div class="mb-2 flex flex-row items-center space-x-2">
												<div><CodeOutline size="lg" /></div>
												<div>Code Interpreter Code</div>
											</div>
											<pre style="white-space: pre-wrap;" class="text-black">{content.code}</pre>
										</div>
									{:else}
										<div class="w-full leading-6">
											<Accordion flush>
												<AccordionItem>
													<span slot="header"
														><div class="flex flex-row items-center space-x-2">
															<div><CodeOutline size="lg" /></div>
															<div>Code Interpreter Code</div>
														</div></span
													>
													<pre
														style="white-space: pre-wrap;"
														class="text-black">{content.code}</pre>
												</AccordionItem>
											</Accordion>
										</div>
									{/if}
								{:else if content.type === 'code_interpreter_call_placeholder'}
									<Card padding="md" class="flex max-w-full flex-row items-center justify-between">
										<div class="flex flex-row items-center space-x-2">
											<div><CodeOutline size="lg" /></div>
											<div>Code Interpreter</div>
										</div>

										<div class="flex flex-wrap items-center gap-2">
											<Button
												outline
												disabled={$loading || $submitting || $waiting}
												pill
												size="xs"
												color="alternative"
												onclick={() => fetchCodeInterpreterResult(content)}
												ontouchstart={() => fetchCodeInterpreterResult(content)}
											>
												Load Code Interpreter Results
											</Button>
										</div></Card
									>
								{:else if content.type === 'file_search_call'}
									<FileSearchCallItem {content} forceOpen={printingThread} />
								{:else if content.type === 'web_search_call'}
									<WebSearchCallItem
										{content}
										forceOpen={printingThread}
										forceEagerImages={printingThread}
									/>
								{:else if content.type === 'mcp_server_call'}
									<MCPServerCallItem {content} forceOpen={printingThread} />
								{:else if content.type === 'mcp_list_tools_call'}
									<MCPListToolsCallItem {content} forceOpen={printingThread} />
								{:else if content.type === 'reasoning'}
									<ReasoningCallItem {content} forceOpen={printingThread} />
								{:else if content.type === 'code_output_image_file'}
									{#if printingThread}
										<div class="w-full leading-6">
											<div class="mb-2 flex flex-row items-center space-x-2">
												<div><ImageSolid size="lg" /></div>
												<div>Output Image</div>
											</div>
											<div class="w-full leading-6">
												<img
													class="img-attachment m-auto"
													src={api.fullPath(
														`/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
													)}
													alt="Attachment generated by the assistant"
												/>
											</div>
										</div>
									{:else}
										<Accordion flush>
											<AccordionItem>
												<span slot="header"
													><div class="flex flex-row items-center space-x-2">
														<div><ImageSolid size="lg" /></div>
														<div>Output Image</div>
													</div></span
												>
												<div class="w-full leading-6">
													<img
														class="img-attachment m-auto"
														src={api.fullPath(
															`/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
														)}
														alt="Attachment generated by the assistant"
													/>
												</div>
											</AccordionItem>
										</Accordion>
									{/if}
								{:else if content.type === 'code_output_image_url'}
									{#if printingThread}
										<div class="w-full leading-6">
											<div class="mb-2 flex flex-row items-center space-x-2">
												<div><ImageSolid size="lg" /></div>
												<div>Output Image</div>
											</div>
											<div class="w-full leading-6">
												<img
													class="img-attachment m-auto"
													src={content.url}
													alt="Attachment generated by the assistant"
												/>
											</div>
										</div>
									{:else}
										<Accordion flush>
											<AccordionItem>
												<span slot="header"
													><div class="flex flex-row items-center space-x-2">
														<div><ImageSolid size="lg" /></div>
														<div>Output Image</div>
													</div></span
												>
												<div class="w-full leading-6">
													<img
														class="img-attachment m-auto"
														src={content.url}
														alt="Attachment generated by the assistant"
													/>
												</div>
											</AccordionItem>
										</Accordion>
									{/if}
								{:else if content.type === 'code_output_logs'}
									{#if printingThread}
										<div class="w-full leading-6">
											<div class="mb-2 flex flex-row items-center space-x-2">
												<div><TerminalOutline size="lg" /></div>
												<div>Output Logs</div>
											</div>
											<div class="w-full leading-6">
												<pre style="white-space: pre-wrap;" class="text-black">{content.logs}</pre>
											</div>
										</div>
									{:else}
										<Accordion flush>
											<AccordionItem>
												<span slot="header"
													><div class="flex flex-row items-center space-x-2">
														<div><TerminalOutline size="lg" /></div>
														<div>Output Logs</div>
													</div></span
												>
												<div class="w-full leading-6">
													<pre
														style="white-space: pre-wrap;"
														class="text-black">{content.logs}</pre>
												</div>
											</AccordionItem>
										</Accordion>
									{/if}
								{:else if content.type === 'image_file'}
									<div class="w-full leading-6">
										<img
											class="img-attachment m-auto"
											src={api.fullPath(
												`/class/${classId}/thread/${threadId}/image/${content.image_file.file_id}`
											)}
											alt="Attachment generated by the assistant"
										/>
									</div>
								{:else}
									<div class="leading-6"><pre>{JSON.stringify(content, null, 2)}</pre></div>
								{/if}
							{/if}
						{/each}
						{#if attachment_file_ids.size > 0}
							<div class="mt-4 flex flex-wrap gap-2">
								{#each attachment_file_ids as file_id (file_id)}
									{#if allFiles[file_id]}
										<FilePlaceholder
											info={allFiles[file_id]}
											mimeType={data.uploadInfo.mimeType}
											on:delete={removeFile}
										/>
									{:else}
										<AttachmentDeletedPlaceholder {file_id} />
									{/if}
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>
		<Modal title="Group Moderators" bind:open={showModerators} autoclose outsideclose
			><ModeratorsTable moderators={teachers} /></Modal
		>
		<Modal title="Assistant Prompt" size="lg" bind:open={showAssistantPrompt} autoclose outsideclose
			><span class="whitespace-pre-wrap text-gray-700"
				><Sanitize html={$threadInstructions ?? ''} /></span
			></Modal
		>
		<Modal title="Copy Link" bind:open={copyLinkModalOpen} autoclose outsideclose>
			<div class="flex flex-col gap-3 p-1">
				<span class="text-sm text-gray-700">Press Cmd+C / Ctrl+C to copy the thread link.</span>
				<input
					class="w-full rounded-md border border-gray-300 bg-gray-50 px-2 py-1 text-sm text-gray-800"
					readonly
					bind:this={shareLinkInputEl}
					value={shareLink}
				/>
				<div class="flex justify-end pt-1">
					<Button size="xs" color="alternative" onclick={() => (copyLinkModalOpen = false)}
						>Done</Button
					>
				</div>
			</div>
		</Modal>
		{#if !$loading}
			<div class="print-hide">
				{#if data.threadInteractionMode === 'voice' && !microphoneAccess && $messages.length === 0 && assistantInteractionMode === 'voice'}
					{#if $isFirefox}
						<div class="flex h-full w-full flex-col items-center justify-center gap-4">
							<div class="rounded-lg bg-blue-light-50 p-3">
								<MicrophoneSlashOutline size="xl" class="text-blue-dark-40" />
							</div>
							<div class="flex w-2/5 flex-col items-center">
								<p class="text-center text-xl font-semibold text-blue-dark-40">
									Voice mode not available on Firefox
								</p>
								<p class="font-base text-center text-base text-gray-600">
									We're working on bringing Voice mode to Firefox in a future update. For the best
									experience, please use Safari, Chrome, or Edge in the meantime.
								</p>
							</div>
						</div>
					{:else}
						<div class="flex h-full w-full flex-col items-center justify-center gap-4">
							<div class="rounded-lg bg-blue-light-50 p-3">
								<MicrophoneOutline size="xl" class="text-blue-dark-40" />
							</div>
							<div class="flex w-2/5 flex-col items-center">
								<p class="text-center text-xl font-semibold text-blue-dark-40">Voice mode</p>
								<p class="font-base text-center text-base text-gray-600">
									To get started, enable microphone access.
								</p>
							</div>
							<Button
								class="flex flex-row gap-1.5 rounded-sm bg-blue-dark-40 px-4 py-1.5 text-center text-sm text-xs font-normal text-white transition-all hover:bg-blue-dark-50 hover:text-blue-light-50"
								type="button"
								onclick={handleSessionSetup}
								ontouchstart={handleSessionSetup}
							>
								Enable access
							</Button>
						</div>
					{/if}
				{:else if data.threadInteractionMode === 'voice' && microphoneAccess && $messages.length === 0 && assistantInteractionMode === 'voice'}
					{#if $isFirefox}
						<div class="flex h-full w-full flex-col items-center justify-center gap-4">
							<div class="rounded-lg bg-blue-light-50 p-3">
								<MicrophoneSlashOutline size="xl" class="text-blue-dark-40" />
							</div>
							<div class="flex w-2/5 flex-col items-center">
								<p class="text-center text-xl font-semibold text-blue-dark-40">
									Voice mode not available on Firefox
								</p>
								<p class="font-base text-center text-base text-gray-600">
									We're working on bringing Voice mode to Firefox in a future update. For the best
									experience, please use Safari, Chrome, or Edge in the meantime.
								</p>
							</div>
						</div>
					{:else}
						<div class="flex h-full w-full flex-col items-center justify-center gap-4">
							<div class="rounded-lg bg-blue-light-50 p-3">
								<MicrophoneOutline size="xl" class="text-blue-dark-40" />
							</div>
							<div class="flex w-2/5 flex-col items-center">
								<p class="text-center text-xl font-semibold text-blue-dark-40">Voice mode</p>
								{#if endingAudioSession}
									<p class="font-base text-center text-base text-gray-600">
										Finishing up your session...
									</p>
								{:else}
									<p class="font-base text-center text-base text-gray-600">
										When you're ready, start the session to begin recording.
									</p>
								{/if}
							</div>
							{#if !isPrivate && displayUserInfo}
								<div
									class="my-5 flex max-w-sm flex-col items-center justify-center gap-1 rounded-2xl border border-red-600 px-3 py-2 text-center"
								>
									<UsersSolid class="h-10 w-10 text-red-600" />
									<span class="text-sm font-normal text-gray-700"
										><Button
											class="p-0 text-sm font-normal text-gray-700 underline"
											onclick={showModeratorsModal}
											ontouchstart={showModeratorsModal}>Moderators</Button
										> have enabled a setting for this thread only that allows them to see the thread,
										<span class="font-semibold"
											>your full name, and listen to a recording of your conversation</span
										>.</span
									>
								</div>
							{/if}
							<div class="flex w-full justify-center">
								<div
									class="flex h-fit w-fit flex-row items-center justify-center gap-2 rounded-xl bg-gray-100 px-2 py-1.5 shadow-xl"
								>
									{#if !audioSessionStarted}
										<Button
											class="flex flex-row gap-1 rounded-lg bg-blue-dark-40 px-3 py-2 text-center text-sm font-normal text-white transition-all hover:bg-blue-dark-50"
											type="button"
											onclick={handleSessionStart}
											ontouchstart={handleSessionStart}
											disabled={!microphoneAccess}
										>
											{#if startingAudioSession}
												<Spinner color="custom" customColor="fill-white" class="mr-1 h-4 w-4" />
											{:else}
												<PlaySolid class="ml-0 pl-0" size="md" />
											{/if}
											<span class="mr-1">Start session</span>
										</Button>
									{:else}
										<Button
											class="flex flex-row gap-1 rounded-lg bg-amber-700 px-3 py-2 text-center text-sm font-normal text-white transition-all hover:bg-amber-800"
											type="button"
											onclick={handleSessionEnd}
											ontouchstart={handleSessionEnd}
											disabled={!microphoneAccess}
										>
											{#if endingAudioSession}
												<Spinner color="custom" customColor="fill-white" class="mr-1 h-4 w-4" />
											{:else}
												<StopSolid class="ml-0 pl-0" size="md" />
											{/if}
											<span class="mr-1">End session</span>
										</Button>
									{/if}
									<Button
										id="top-dd"
										class="flex max-w-56 min-w-56 shrink-0 grow-0 flex-row justify-between gap-2 rounded-lg px-3 py-2 text-sm font-normal text-gray-800 transition-all hover:bg-gray-300"
										disabled={!microphoneAccess ||
											audioSessionStarted ||
											startingAudioSession ||
											endingAudioSession}
									>
										<div class="flex w-5/6 flex-row justify-start gap-2">
											<MicrophoneOutline class="h-5 w-5" />
											<span class="truncate"
												>{selectedAudioDevice?.label || 'Select microphone...'}</span
											>
										</div>
										<ChevronSortOutline class="ml-2 h-4 w-4" strokeWidth="2" /></Button
									>
									{#if audioDevices.length === 0}
										<Dropdown placement="top" triggeredBy="#top-dd" bind:open={openMicrophoneModal}>
											<DropdownItem class="flex flex-row items-center gap-2">
												<span>No microphones available</span>
											</DropdownItem>
										</Dropdown>
									{:else}
										<Dropdown placement="top" triggeredBy="#top-dd" bind:open={openMicrophoneModal}>
											{#each audioDevices as audioDevice (audioDevice.deviceId)}
												<DropdownItem
													class="flex flex-row items-center gap-2"
													onclick={() => {
														selectAudioDevice(audioDevice.deviceId);
														openMicrophoneModal = false;
													}}
												>
													{#if audioDevice.deviceId === selectedAudioDevice?.deviceId}
														<CheckOutline class="h-5 w-5" />
													{:else}
														<span class="h-5 w-5"></span>
													{/if}
													<span>{audioDevice.label}</span>
												</DropdownItem>
											{/each}
										</Dropdown>
									{/if}
								</div>
							</div>
						</div>
					{/if}
				{/if}

				<div class="w-full bg-gradient-to-t from-white to-transparent">
					<div class="relative mx-auto flex w-11/12 flex-col">
						<StatusErrors {assistantStatusUpdates} />
						{#if data.threadInteractionMode == 'chat' && assistantInteractionMode === 'chat'}
							{#if $waiting || $submitting}
								<div
									class="absolute -top-10 flex w-full justify-center"
									transition:blur={{ amount: 10 }}
								>
									<DoubleBounce color="#0ea5e9" size="30" />
								</div>
							{/if}
							{#key threadId}
								<ChatInput
									bind:this={chatInputRef}
									mimeType={data.uploadInfo.mimeType}
									maxSize={data.uploadInfo.private_file_max_size}
									bind:attachments={currentMessageAttachments}
									{threadManagerError}
									visionAcceptedFiles={chatVisionAcceptedFiles}
									fileSearchAcceptedFiles={chatFileSearchAcceptedFiles}
									codeInterpreterAcceptedFiles={chatCodeInterpreterAcceptedFiles}
									{visionSupportOverride}
									{useImageDescriptions}
									{assistantDeleted}
									{canViewAssistant}
									canSubmit={canSubmit && !assistantDeleted && canViewAssistant}
									disabled={chatInputDisabled}
									loading={$submitting || $waiting}
									{fileSearchAttachmentCount}
									{codeInterpreterAttachmentCount}
									upload={handleUpload}
									remove={handleRemove}
									threadVersion={$version}
									assistantVersion={resolvedAssistantVersion}
									{bypassedSettingsSections}
									on:submit={handleSubmit}
									on:dismissError={handleDismissError}
									on:startNewChat={startNewChat}
								/>
							{/key}
						{:else if data.threadInteractionMode === 'voice' && ($messages.length > 0 || assistantInteractionMode === 'chat')}
							{#if threadRecording && $messages.length > 0 && assistantInteractionMode === 'voice'}
								<div
									class="relative z-10 -mb-3 flex flex-wrap gap-2 rounded-t-2xl border border-b-0 border-gray-500 bg-gray-100 px-3.5 pt-2.5 pb-5 text-blue-dark-40"
								>
									<div class="w-full">
										{#if showPlayer && audioUrl}
											<AudioPlayer bind:src={audioUrl} duration={threadRecording.duration} />
										{:else}
											<div class="flex w-full flex-col items-center gap-2 md:flex-row">
												<div class="text-danger-000 flex flex-row items-center gap-2 md:w-full">
													<div class="flex w-fit flex-col">
														<div class="text-xs font-semibold uppercase">Recording available</div>
														<div class="text-sm">
															You can listen to a recording of this conversation.
														</div>
													</div>
												</div>
												<Button
													class="w-fit shrink-0 rounded-lg bg-gradient-to-b from-blue-dark-30 to-blue-dark-40 px-2 py-1 text-xs font-normal text-white transition-all hover:from-blue-dark-40 hover:to-blue-dark-50"
													onclick={fetchRecording}
												>
													Load Recording
												</Button>
											</div>
										{/if}
									</div>
								</div>
							{/if}

							<div
								class="relative z-20 flex flex-col items-stretch gap-2 rounded-2xl border border-melon bg-seasalt py-2.5 pr-3 pl-4 shadow-[0_0.25rem_1.25rem_rgba(254,184,175,0.15)] transition-all duration-200 focus-within:border-coral-pink focus-within:shadow-[0_0.25rem_1.25rem_rgba(253,148,134,0.25)] hover:border-coral-pink"
							>
								<div class="flex flex-row gap-2">
									<MicrophoneOutline class="h-6 w-6 text-gray-700" />
									<div class="flex flex-col">
										<span class="text-base font-semibold text-gray-700">Voice Mode Session</span
										><span class="text-base font-normal text-gray-700"
											>This conversation was completed in Voice mode and is read-only. To continue
											chatting, start a new conversation.</span
										>
									</div>
								</div>
							</div>
						{:else if data.threadInteractionMode === 'chat' && assistantInteractionMode === 'voice'}
							<div
								class="relative z-20 flex flex-col items-stretch gap-2 rounded-2xl border border-melon bg-seasalt py-2.5 pr-3 pl-4 shadow-[0_0.25rem_1.25rem_rgba(254,184,175,0.15)] transition-all duration-200 focus-within:border-coral-pink focus-within:shadow-[0_0.25rem_1.25rem_rgba(253,148,134,0.25)] hover:border-coral-pink"
							>
								<div class="flex flex-row gap-2">
									<MicrophoneOutline class="h-6 w-6 text-gray-700" />
									<div class="flex flex-col">
										<span class="text-base font-semibold text-gray-700"
											>Assistant in Voice mode</span
										><span class="text-base font-normal text-gray-700"
											>This assistant uses audio. Start a new session to keep the conversation
											going.</span
										>
									</div>
								</div>
							</div>
						{/if}
						<div class="my-3 flex w-full grow items-center justify-between gap-2 text-sm">
							<div class="flex min-w-0 shrink grow gap-2">
								{#if !$published && isPrivate && !displayUserInfo}
									<LockSolid size="sm" class="text-orange" />
									<Span class="text-xs font-normal text-gray-600"
										><Button
											class="p-0 text-xs font-normal text-gray-600 underline"
											onclick={showModeratorsModal}
											ontouchstart={showModeratorsModal}>Moderators</Button
										> <span class="font-semibold">cannot</span> see this thread or your name. {#if isCurrentUser}For
											more information, please review <a
												href={resolve('/privacy-policy')}
												rel="noopener noreferrer"
												class="underline">PingPong's privacy statement</a
											>.
										{/if}Assistants can make mistakes. Check important info.</Span
									>
								{:else if !$published}
									{#if displayUserInfo}
										{#if data.threadInteractionMode === 'voice'}
											<div class="flex w-full flex-wrap items-start gap-2 text-sm lg:flex-nowrap">
												<UsersSolid size="sm" class="pt-0 text-orange" />
												<Span class="text-xs font-normal text-gray-600"
													><Button
														class="p-0 text-xs font-normal text-gray-600 underline"
														onclick={showModeratorsModal}
														ontouchstart={showModeratorsModal}>Moderators</Button
													> can see this thread,
													<span class="font-semibold"
														>{isCurrentUser ? 'your' : "the user's"} full name, and listen to a recording
														of {isCurrentUser ? 'your' : 'the'} conversation</span
													>. For more information, please review
													<a
														href={resolve('/privacy-policy')}
														rel="noopener noreferrer"
														class="underline">PingPong's privacy statement</a
													>. Assistants can make mistakes. Check important info.</Span
												>
											</div>
										{:else}
											<div class="flex w-full flex-wrap items-start gap-2 text-sm lg:flex-nowrap">
												<UsersSolid size="sm" class="pt-0 text-orange" />
												<Span class="text-xs font-normal text-gray-600"
													><Button
														class="p-0 text-xs font-normal text-gray-600 underline"
														onclick={showModeratorsModal}
														ontouchstart={showModeratorsModal}>Moderators</Button
													> can see this thread and
													<span class="font-semibold"
														>{isCurrentUser ? 'your' : "the user's"} full name</span
													>. For more information, please review
													<a
														href={resolve('/privacy-policy')}
														rel="noopener noreferrer"
														class="underline">PingPong's privacy statement</a
													>. Assistants can make mistakes. Check important info.</Span
												>
											</div>
										{/if}
									{:else}
										<EyeSlashOutline size="sm" class="text-orange" />
										<Span class="text-xs font-normal text-gray-600"
											><Button
												class="p-0 text-xs font-normal text-gray-600 underline"
												onclick={showModeratorsModal}
												ontouchstart={showModeratorsModal}>Moderators</Button
											> can see this thread but not {isCurrentUser ? 'your' : "the user's"} name.
											{#if isCurrentUser}For more information, please review <a
													href={resolve('/privacy-policy')}
													rel="noopener noreferrer"
													class="underline">PingPong's privacy statement</a
												>.
											{/if}Assistants can make mistakes. Check important info.</Span
										>
									{/if}
								{:else}
									<EyeOutline size="sm" class="text-orange" />
									<Span class="text-xs font-normal text-gray-600"
										>Everyone in this group can see this thread but not {isCurrentUser
											? 'your'
											: "the user's"} name. {#if displayUserInfo}{#if data.threadInteractionMode === 'voice'}<Button
													class="p-0 text-xs font-normal text-gray-600 underline"
													onclick={showModeratorsModal}
													ontouchstart={showModeratorsModal}>Moderators</Button
												> can see this thread,
												<span class="font-semibold"
													>{isCurrentUser ? 'your' : "the user's"} full name, and listen to a recording
													of
													{isCurrentUser ? 'your' : 'the'} conversation</span
												>.{:else}<Button
													class="p-0 text-xs font-normal text-gray-600 underline"
													onclick={showModeratorsModal}
													ontouchstart={showModeratorsModal}>Moderators</Button
												> can see this thread and
												<span class="font-semibold"
													>{isCurrentUser ? 'your' : "the user's"} full name</span
												>.{/if}{/if} Assistants can make mistakes. Check important info.</Span
									>
								{/if}
							</div>
							<button onclick={handleCopyLinkClick} title="Copy link" aria-label="Copy link"
								><LinkOutline
									class="inline-block h-6 w-5 font-medium text-blue-dark-30 hover:text-blue-dark-50 active:animate-ping dark:text-white"
									size="lg"
								/></button
							>
							{#if !(data.threadInteractionMode === 'voice' && $messages.length === 0 && assistantInteractionMode === 'voice')}
								<div class="h-auto shrink-0 grow-0">
									<CogOutline class="h-4 w-6 cursor-pointer font-light dark:text-white" size="lg" />
									<Dropdown bind:open={settingsOpen}>
										{#if $threadInstructions}
											<DropdownItem
												onclick={() => ((showAssistantPrompt = true), (settingsOpen = false))}
											>
												<span>Prompt</span>
											</DropdownItem>
											<DropdownDivider />
										{/if}
										<DropdownItem onclick={handlePrintThread} disabled={printingThread}>
											<span class:text-gray-300={printingThread}>Print</span>
										</DropdownItem>
										{#if threadRecording}
											<DropdownItem onclick={transcribeRecording} disabled={transcribingRecording}>
												<span class:text-gray-300={transcribingRecording}>Transcribe</span>
											</DropdownItem>
										{/if}
										<DropdownDivider />
										<DropdownItem onclick={togglePublish} disabled={!canPublishThread}>
											<span class:text-gray-300={!canPublishThread}>
												{#if $published}
													Unpublish
												{:else}
													Publish
												{/if}
											</span>
										</DropdownItem>
										<DropdownItem onclick={deleteThread} disabled={!canDeleteThread}>
											<span class:text-gray-300={!canDeleteThread}>Delete</span>
										</DropdownItem>
									</Dropdown>
								</div>
							{/if}
						</div>
					</div>
				</div>
			</div>
		{/if}
	{/if}
	<ChatDropOverlay visible={dropOverlayVisible && canDropUploadsIntoThread} />
</div>

<style lang="css">
	.img-attachment {
		max-width: min(95%, 700px);
	}

	.print-only {
		display: none;
	}

	@media print {
		.print-only {
			display: block;
		}

		.print-header {
			border: 1px solid #e5e7eb;
			background: #ffffff;
			padding: 16px;
			border-radius: 12px;
			font-family: inherit;
			color: #0f172a;
			box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
			margin-bottom: 18px;
		}

		.print-header__brand {
			display: flex;
			align-items: center;
			gap: 10px;
			margin-bottom: 10px;
		}

		.print-header__brand-text {
			font-size: 1rem;
			font-weight: 700;
			letter-spacing: 0.02em;
		}

		.print-header__meta {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
			gap: 8px 14px;
			margin-bottom: 10px;
			font-size: 0.95rem;
		}

		.print-header__meta .label {
			display: inline-block;
			min-width: 60px;
			font-weight: 600;
			color: #0f172a;
			margin-right: 6px;
		}

		.print-header__link {
			font-size: 0.84rem;
			color: #111827;
			word-break: break-all;
			padding-top: 6px;
			border-top: 1px dashed #d1d5db;
			margin-top: 6px;
		}

		/* Hide chat input and footer during print */
		.print-hide {
			display: none !important;
		}

		/* Make messages container full height and overflow visible */
		.messages-container {
			overflow: visible !important;
			height: auto !important;
			max-height: none !important;
		}
	}
</style>
