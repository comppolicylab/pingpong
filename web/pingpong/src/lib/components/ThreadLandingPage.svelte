<script lang="ts">
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { navigating, page } from '$app/stores';
	import ChatInput, { type ChatInputMessage } from '$lib/components/ChatInput.svelte';
	import ChatDropOverlay from '$lib/components/ChatDropOverlay.svelte';
	import {
		Button,
		Span,
		Modal,
		Dropdown,
		DropdownItem,
		DropdownDivider,
		Tooltip
	} from 'flowbite-svelte';
	import {
		EyeSlashOutline,
		LockSolid,
		MicrophoneOutline,
		ClapperboardPlayOutline,
		CirclePlusSolid,
		MicrophoneSlashOutline,
		BadgeCheckOutline,
		UsersOutline,
		ChevronSortOutline,
		CheckCircleSolid,
		UserOutline,
		PaperPlaneOutline,
		UsersSolid,
		QuestionCircleOutline
	} from 'flowbite-svelte-icons';
	import { sadToast } from '$lib/toast';
	import * as api from '$lib/api';
	import { hasAnonymousSessionToken, setAnonymousSessionToken } from '$lib/stores/anonymous';
	import { errorMessage } from '$lib/errors';
	import { computeLatestIncidentTimestamps, filterLatestIncidentUpdates } from '$lib/statusUpdates';
	import type { Assistant, FileUploadPurpose } from '$lib/api';
	import { loading, isFirefox } from '$lib/stores/general';
	import DropdownBadge from '$lib/components/DropdownBadge.svelte';
	import ModeratorsTable from '$lib/components/ModeratorsTable.svelte';
	import StatusErrors from './StatusErrors.svelte';

	/**
	 * Application data.
	 */
	export let data;
	$: conversationId = $page.url.searchParams.get('conversation_id');
	type ChatInputHandle = { addFiles: (selectedFiles: File[]) => void };
	let chatInputRef: ChatInputHandle | null = null;
	let dropOverlayVisible = false;
	let dropDragCounter = 0;

	const errorMessages: Record<number, string> = {
		1: 'We faced an issue when trying to sync with Canvas.'
	};

	// Function to get error message from error code
	function getErrorMessage(errorCode: number) {
		return (
			errorMessages[errorCode] || 'An unknown error occurred while trying to sync with Canvas.'
		);
	}

	afterNavigate(async () => {
		const errorCode = $page.url.searchParams.get('error_code');
		if (errorCode) {
			const errorMessage = getErrorMessage(parseInt(errorCode) || 0);
			sadToast(errorMessage);
		}
		// Make sure that an assistant is linked in the URL
		if (!$page.url.searchParams.has('assistant') && !data.isSharedAssistantPage) {
			if (data.assistants.length > 0) {
				// replace current URL with one that has the assistant ID
				await goto(resolve(`/group/${data.class.id}/?assistant=${data.assistants[0].id}`), {
					replaceState: true
				});
			}
		}
	});

	// Get info about assistant provenance
	const getAssistantMetadata = (assistant: Assistant) => {
		const isCourseAssistant = assistant.endorsed;
		const isMyAssistant = data.me.user && assistant.creator_id === data.me.user.id;
		const creator = data.assistantCreators[assistant.creator_id]?.name || 'Unknown creator';
		const willDisplayUserInfo = data.class.private
			? false
			: (assistant.should_record_user_information ?? false);
		return {
			creator: isCourseAssistant ? 'Moderation Team' : creator,
			isCourseAssistant,
			isMyAssistant,
			willDisplayUserInfo
		};
	};

	let userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
	$: isPrivate = data.class.private || false;
	// Currently selected assistant.
	$: assistants = data?.assistants || [];
	$: teachers = data?.supervisors || [];
	$: courseAssistants = assistants.filter((asst: Assistant) => asst.endorsed);
	$: myAssistantsAll = assistants.filter((asst: Assistant) => asst.creator_id === data.me.user?.id);
	$: myAssistants = myAssistantsAll.filter((asst: Assistant) => !asst.endorsed);
	$: otherAssistantsAll = assistants.filter(
		(asst: Assistant) => asst.creator_id !== data.me.user?.id
	);
	$: otherAssistants = otherAssistantsAll.filter((asst: Assistant) => !asst.endorsed);
	let assistant = data?.assistants[0] || {};
	$: assistantMeta = getAssistantMetadata(assistant);
	// Whether billing is set up for the class (which controls everything).
	$: isConfigured = data?.hasAssistants && data?.hasAPIKey;
	$: parties = data.me.status === 'anonymous' ? '' : data.me.user?.id ? `${data.me.user.id}` : '';
	// The assistant ID from the URL.
	$: linkedAssistant = parseInt($page.url.searchParams.get('assistant') || '0', 10);
	let useImageDescriptions = false;
	let allowUserFileUploads = true;
	let allowUserImageUploads = true;
	$: {
		if (linkedAssistant && assistants) {
			const selectedAssistant = (assistants || []).find(
				(asst: Assistant) => asst.id === linkedAssistant
			);
			if (selectedAssistant) {
				assistant = selectedAssistant;
				useImageDescriptions = assistant.use_image_descriptions || false;
				allowUserFileUploads = assistant.allow_user_file_uploads ?? true;
				allowUserImageUploads = assistant.allow_user_image_uploads ?? true;
			}
		}
	}
	$: supportsFileSearch = assistant.tools?.includes('file_search') || false;
	$: supportsCodeInterpreter = assistant.tools?.includes('code_interpreter') || false;
	$: supportsWebSearch = assistant.tools?.includes('web_search') || false;
	$: supportsMCPServer = assistant.tools?.includes('mcp_server') || false;
	let supportsVision = false;
	$: {
		const supportVisionModels = (
			data.modelInfo.filter((model: api.AssistantModelLite) => model.supports_vision) || []
		).map((model: api.AssistantModelLite) => model.id);
		supportsVision = supportVisionModels.includes(assistant.model);
	}
	let visionSupportOverride: boolean | undefined;
	$: {
		visionSupportOverride =
			data.class.ai_provider === 'azure'
				? data.modelInfo.find((model: api.AssistantModelLite) => model.id === assistant.model)
						?.azure_supports_vision
				: undefined;
	}
	$: landingVisionAcceptedFiles =
		allowUserImageUploads && supportsVision
			? data.uploadInfo.fileTypes({
					file_search: false,
					code_interpreter: false,
					vision: true
				})
			: null;
	$: effectiveLandingVisionAcceptedFiles =
		visionSupportOverride === false && !useImageDescriptions ? null : landingVisionAcceptedFiles;
	$: landingFileSearchAcceptedFiles =
		allowUserFileUploads && supportsFileSearch
			? data.uploadInfo.fileTypes({
					file_search: true,
					code_interpreter: false,
					vision: false
				})
			: null;
	$: landingCodeInterpreterAcceptedFiles =
		allowUserFileUploads && supportsCodeInterpreter
			? data.uploadInfo.fileTypes({
					file_search: false,
					code_interpreter: true,
					vision: false
				})
			: null;
	$: canDropUploadsOnLanding =
		isConfigured &&
		assistant.interaction_mode === 'chat' &&
		chatInputRef !== null &&
		!(assistant.assistant_should_message_first ?? false) &&
		!($loading || !!$navigating) &&
		!!(
			effectiveLandingVisionAcceptedFiles ||
			landingFileSearchAcceptedFiles ||
			landingCodeInterpreterAcceptedFiles
		);
	let showModerators = false;

	$: statusComponents = (data.statusComponents || {}) as Partial<
		Record<string, api.StatusComponentUpdate[]>
	>;
	let latestIncidentUpdateTimestamps: Record<string, number> = {};
	$: latestIncidentUpdateTimestamps = computeLatestIncidentTimestamps(statusComponents);
	$: assistantVersionNumber = Number(assistant?.version ?? 0);
	$: statusComponentId =
		assistantVersionNumber >= 3
			? api.STATUS_COMPONENT_IDS.nextGen
			: api.STATUS_COMPONENT_IDS.classic;
	$: assistantStatusUpdates = filterLatestIncidentUpdates(
		statusComponents[statusComponentId],
		latestIncidentUpdateTimestamps
	);

	// Handle file upload
	const handleUpload = (
		f: File,
		onProgress: (p: number) => void,
		purpose: FileUploadPurpose = 'assistants',
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
		if (api.isErrorResponse(result)) {
			sadToast(`Failed to delete file. Error: ${result.detail || 'unknown error'}`);
			throw new Error(result.detail || 'unknown error');
		}
	};

	const isFileDrag = (event: DragEvent) =>
		Array.from(event.dataTransfer?.types ?? []).includes('Files');

	const resetDropOverlay = () => {
		dropOverlayVisible = false;
		dropDragCounter = 0;
	};

	const handleWindowDragEnd = (event: DragEvent) => {
		event.preventDefault();
		event.stopPropagation();
		resetDropOverlay();
	};

	const handleWindowDrop = (event: DragEvent) => {
		event.preventDefault();
		event.stopPropagation();
		resetDropOverlay();
	};

	const handleLandingDragEnter = (event: DragEvent) => {
		const fileDrag = isFileDrag(event);
		if (fileDrag) {
			event.preventDefault();
			event.stopPropagation();
		}
		if (!canDropUploadsOnLanding || !fileDrag) {
			return;
		}
		dropDragCounter += 1;
		dropOverlayVisible = true;
	};

	const handleLandingDragOver = (event: DragEvent) => {
		event.preventDefault();
		event.stopPropagation();
		if (!canDropUploadsOnLanding || !isFileDrag(event)) {
			return;
		}
		if (event.dataTransfer) {
			event.dataTransfer.dropEffect = 'copy';
		}
		dropOverlayVisible = true;
	};

	const handleLandingDragLeave = (event: DragEvent) => {
		const fileDrag = isFileDrag(event);
		if (fileDrag) {
			event.preventDefault();
			event.stopPropagation();
		}
		if (!canDropUploadsOnLanding || !fileDrag) {
			return;
		}
		dropDragCounter = Math.max(0, dropDragCounter - 1);
		if (dropDragCounter === 0) {
			dropOverlayVisible = false;
		}
	};

	const handleLandingDrop = (event: DragEvent) => {
		const fileDrag = isFileDrag(event);
		if (fileDrag) {
			event.preventDefault();
			event.stopPropagation();
		}
		if (!canDropUploadsOnLanding || !fileDrag) {
			dropOverlayVisible = false;
			dropDragCounter = 0;
			return;
		}
		const droppedFiles = Array.from(event.dataTransfer?.files ?? []);
		resetDropOverlay();
		if (!droppedFiles.length) {
			return;
		}
		chatInputRef?.addFiles(droppedFiles);
	};

	const handleAudioThreadCreate = async () => {
		$loading = true;
		const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
		try {
			const newThreadOpts = api.explodeResponse(
				await api.createAudioThread(fetch, data.class.id, {
					assistant_id: assistant.id,
					parties: partyIds,
					timezone: userTimezone,
					conversation_id:
						data.isSharedAssistantPage || data.isSharedThreadPage ? conversationId : null
				})
			);
			data.threads = [newThreadOpts.thread as api.Thread, ...data.threads];
			setAnonymousSessionToken(newThreadOpts.session_token || null);
			$loading = false;
			if (hasAnonymousSessionToken()) {
				await goto(
					resolve(`/group/${$page.params.classId}/shared/thread/${newThreadOpts.thread.id}`)
				);
			} else {
				await goto(resolve(`/group/${$page.params.classId}/thread/${newThreadOpts.thread.id}`));
			}
		} catch (e) {
			$loading = false;
			sadToast(
				`Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check PingPong's status page for updates.")}`
			);
		}
	};

	const handleLectureThreadCreate = async () => {
		if ($loading) return;
		$loading = true;
		const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
		try {
			const newThreadOpts = api.explodeResponse(
				await api.createLectureThread(fetch, data.class.id, {
					assistant_id: assistant.id,
					parties: partyIds,
					timezone: userTimezone,
					conversation_id:
						data.isSharedAssistantPage || data.isSharedThreadPage ? conversationId : null
				})
			);
			data.threads = [newThreadOpts.thread as api.Thread, ...data.threads];
			setAnonymousSessionToken(newThreadOpts.session_token || null);
			$loading = false;
			if (hasAnonymousSessionToken()) {
				await goto(
					resolve(`/group/${$page.params.classId}/shared/thread/${newThreadOpts.thread.id}`)
				);
			} else {
				await goto(resolve(`/group/${$page.params.classId}/thread/${newThreadOpts.thread.id}`));
			}
		} catch (e) {
			$loading = false;
			sadToast(
				`Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check PingPong's status page for updates.")}`
			);
		}
	};

	const handleChatThreadCreate = async () => {
		$loading = true;
		const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
		const tools: api.Tool[] = [];
		if (supportsFileSearch) {
			tools.push({ type: 'file_search' });
		}
		if (supportsCodeInterpreter) {
			tools.push({ type: 'code_interpreter' });
		}
		if (supportsWebSearch) {
			tools.push({ type: 'web_search' });
		}
		if (supportsMCPServer) {
			tools.push({ type: 'mcp_server' });
		}
		try {
			const newThreadOpts = api.explodeResponse(
				await api.createThread(fetch, data.class.id, {
					assistant_id: assistant.id,
					parties: partyIds,
					message: null,
					tools_available: tools,
					code_interpreter_file_ids: [],
					file_search_file_ids: [],
					vision_file_ids: [],
					vision_image_descriptions: [],
					timezone: userTimezone,
					conversation_id:
						data.isSharedAssistantPage || data.isSharedThreadPage ? conversationId : null
				})
			);
			data.threads = [newThreadOpts.thread as api.Thread, ...data.threads];
			setAnonymousSessionToken(newThreadOpts.session_token || null);
			$loading = false;
			if (hasAnonymousSessionToken()) {
				await goto(
					resolve(`/group/${$page.params.classId}/shared/thread/${newThreadOpts.thread.id}`)
				);
			} else {
				await goto(resolve(`/group/${$page.params.classId}/thread/${newThreadOpts.thread.id}`));
			}
		} catch (e) {
			$loading = false;
			sadToast(
				`Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check PingPong's status page for updates.")}`
			);
		}
	};

	// Handle form submission
	const handleSubmit = async (e: CustomEvent<ChatInputMessage>) => {
		$loading = true;
		const form = e.detail;
		if (!form.message) {
			$loading = false;
			form.callback({
				success: false,
				errorMessage: 'Please enter a message.',
				message_sent: false
			});
			return;
		}

		const partyIds = parties ? parties.split(',').map((id) => parseInt(id, 10)) : [];
		const tools: api.Tool[] = [];
		if (supportsFileSearch) {
			tools.push({ type: 'file_search' });
		}
		if (supportsCodeInterpreter) {
			tools.push({ type: 'code_interpreter' });
		}
		if (supportsWebSearch) {
			tools.push({ type: 'web_search' });
		}
		if (supportsMCPServer) {
			tools.push({ type: 'mcp_server' });
		}

		try {
			const newThreadOpts = api.explodeResponse(
				await api.createThread(fetch, data.class.id, {
					assistant_id: assistant.id,
					parties: partyIds,
					message: form.message,
					tools_available: tools,
					code_interpreter_file_ids: form.code_interpreter_file_ids,
					file_search_file_ids: form.file_search_file_ids,
					vision_file_ids: form.vision_file_ids,
					vision_image_descriptions: form.visionFileImageDescriptions,
					conversation_id:
						data.isSharedAssistantPage || data.isSharedThreadPage ? conversationId : null
				})
			);
			data.threads = [newThreadOpts.thread as api.Thread, ...data.threads];
			setAnonymousSessionToken(newThreadOpts.session_token || null);
			$loading = false;
			form.callback({ success: true, errorMessage: null, message_sent: true });
			if (hasAnonymousSessionToken()) {
				await goto(
					resolve(`/group/${$page.params.classId}/shared/thread/${newThreadOpts.thread.id}`)
				);
			} else {
				await goto(resolve(`/group/${$page.params.classId}/thread/${newThreadOpts.thread.id}`));
			}
		} catch (e) {
			$loading = false;
			form.callback({
				success: false,
				errorMessage: `Failed to create thread. Error: ${errorMessage(e, "Something went wrong while creating your conversation. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.")}`,
				message_sent: false
			});
		}
	};

	let assistantDropdownOpen = false;
	// Set the new assistant selection.
	const selectAi = async (asst: Assistant) => {
		assistantDropdownOpen = false;
		await goto(resolve(`/group/${data.class.id}/?assistant=${asst.id}`));
	};
	const showModeratorsModal = () => {
		showModerators = true;
	};
</script>

<svelte:window ondragend={handleWindowDragEnd} ondrop={handleWindowDrop} />

<div
	class="relative flex min-h-0 shrink grow justify-center"
	role="region"
	aria-label="Thread landing"
	ondragenter={handleLandingDragEnter}
	ondragover={handleLandingDragOver}
	ondragleave={handleLandingDragLeave}
	ondrop={handleLandingDrop}
>
	<div
		class="flex h-full w-11/12 flex-col justify-between transition-opacity ease-in"
		class:opacity-0={$loading}
	>
		{#if isConfigured}
			<Modal title="Group Moderators" bind:open={showModerators} autoclose outsideclose>
				<ModeratorsTable moderators={teachers} />
			</Modal>
			<div class="flex h-full w-full flex-col items-center justify-center gap-4 overflow-auto">
				<div class="flex w-full flex-col items-center gap-2 text-center md:w-2/3 lg:w-1/2">
					<div class="flex flex-col items-center justify-center gap-1">
						<div class="text-xl leading-tight font-medium md:text-4xl">{assistant.name}</div>
					</div>
					{#if !(data.isSharedAssistantPage || data.isSharedThreadPage)}
						<div
							class="flex flex-row items-center gap-1 text-xs font-normal text-gray-400 sm:text-sm"
						>
							{#if assistantMeta.isCourseAssistant}
								<BadgeCheckOutline class="h-4 w-4 sm:h-5 sm:w-5" />
								<span>Group assistant</span>
							{:else if assistantMeta.isMyAssistant}
								<UserOutline class="h-4 w-4 sm:h-5 sm:w-5" />
								<span>Created by you</span>
							{:else}
								<UsersOutline class="h-4 w-4 sm:h-5 sm:w-5" />
								<span>Created by {assistantMeta.creator}</span>
							{/if}
						</div>
					{/if}
					{#if assistant.description}
						<div class="text-sm text-gray-700">{assistant.description}</div>
					{/if}
					{#if assistants.length > 1}
						<Button
							pill
							class={'flex flex-row items-center gap-0.5 border border-gray-300 px-3 py-1 text-xs text-gray-600 transition-all hover:bg-gray-50' +
								(assistantDropdownOpen ? ' bg-gray-50' : '')}
							type="button"
						>
							<span class="text-center text-xs font-normal"> Change assistant </span>
							<ChevronSortOutline class="text-gray-500" size="xs" />
						</Button>
						<Dropdown
							class="h-full p-3"
							classContainer="rounded-3xl lg:w-1/3 md:w-1/2 w-2/3 border border-gray-100 max-h-[40%] overflow-y-auto"
							bind:open={assistantDropdownOpen}
						>
							<!-- Show course assistants first -->
							{#if courseAssistants.length > 0}
								<DropdownItem
									class="pointer-events-none pb-1 font-normal tracking-tight text-gray-400 normal-case select-none hover:bg-none"
								>
									Group assistants
								</DropdownItem>
							{/if}

							{#each courseAssistants as asst (asst.id)}
								<DropdownItem
									onclick={() => selectAi(asst)}
									ontouchstart={() => selectAi(asst)}
									class="group max-w-full rounded-lg font-normal tracking-tight normal-case select-none hover:bg-gray-100"
								>
									<div class="flex max-w-full flex-row items-center justify-between gap-5">
										<div class="flex w-10/12 flex-col gap-1">
											<div class="text-sm leading-snug">
												{#if asst.interaction_mode === 'voice'}
													<MicrophoneOutline
														size="sm"
														class="inline align-text-bottom text-gray-400"
													/>
													<Tooltip>Voice mode assistant</Tooltip>
												{:else if asst.interaction_mode === 'lecture_video'}
													<ClapperboardPlayOutline
														size="sm"
														class="inline align-text-bottom text-gray-400"
													/>
													<Tooltip>Lecture Video mode assistant</Tooltip>
												{/if}
												{asst.name}
											</div>
											{#if asst.description}
												<div class="truncate text-xs text-gray-500">
													{asst.description}
												</div>
											{/if}
										</div>

										{#if assistant.id === asst.id}
											<CheckCircleSolid size="md" class="text-blue-dark-40 group-hover:hidden" />
										{/if}
									</div>
								</DropdownItem>
							{/each}

							<!-- Show a divider if necessary -->
							{#if myAssistants.length > 0 && courseAssistants.length > 0}
								<DropdownDivider />
							{/if}

							<!-- Show the user's assistants -->
							{#if myAssistants.length > 0}
								<DropdownItem
									class="pointer-events-none pb-1 font-normal tracking-tight text-gray-400 normal-case select-none hover:bg-none"
								>
									Your assistants
								</DropdownItem>

								{#each myAssistants as asst (asst.id)}
									<DropdownItem
										onclick={() => selectAi(asst)}
										ontouchstart={() => selectAi(asst)}
										class="group max-w-full rounded-lg font-normal tracking-tight normal-case select-none hover:bg-gray-100"
									>
										<div class="flex max-w-full flex-row items-center justify-between gap-5">
											<div class="flex w-10/12 flex-col gap-1">
												<div class="text-sm leading-snug">
													{#if asst.interaction_mode === 'voice'}
														<MicrophoneOutline
															size="sm"
															class="inline align-text-bottom text-gray-400"
														/>
														<Tooltip>Voice mode assistant</Tooltip>
													{:else if asst.interaction_mode === 'lecture_video'}
														<ClapperboardPlayOutline
															size="sm"
															class="inline align-text-bottom text-gray-400"
														/>
														<Tooltip>Lecture Video mode assistant</Tooltip>
													{/if}
													{asst.name}
												</div>
												{#if asst.description}
													<div class="truncate text-xs text-gray-500">
														{asst.description}
													</div>
												{/if}
											</div>

											{#if assistant.id === asst.id}
												<CheckCircleSolid size="md" class="text-blue-dark-40 group-hover:hidden" />
											{/if}
										</div>
									</DropdownItem>
								{/each}
							{/if}
							<!-- Show a divider if necessary -->
							{#if otherAssistants.length > 0 && (myAssistants.length > 0 || courseAssistants.length > 0)}
								<DropdownDivider />
							{/if}

							<!-- Show the user's assistants -->
							{#if otherAssistants.length > 0}
								<DropdownItem
									class="pointer-events-none pb-1 font-normal tracking-tight text-gray-400 normal-case select-none hover:bg-none"
								>
									Other assistants
								</DropdownItem>

								{#each otherAssistants as asst (asst.id)}
									<DropdownItem
										onclick={() => selectAi(asst)}
										ontouchstart={() => selectAi(asst)}
										class="group max-w-full rounded-sm font-normal tracking-tight normal-case select-none hover:bg-gray-100"
									>
										<div class="flex max-w-full flex-row items-center justify-between gap-5">
											<div class="flex w-10/12 flex-col gap-1">
												<div class="text-sm leading-snug">
													{#if asst.interaction_mode === 'voice'}
														<MicrophoneOutline
															size="sm"
															class="inline align-text-bottom text-gray-400"
														/>
														<Tooltip>Voice mode assistant</Tooltip>
													{:else if asst.interaction_mode === 'lecture_video'}
														<ClapperboardPlayOutline
															size="sm"
															class="inline align-text-bottom text-gray-400"
														/>
														<Tooltip>Lecture Video mode assistant</Tooltip>
													{/if}
													{asst.name}
												</div>
												{#if asst.description}
													<div class="truncate text-xs text-gray-500">
														{asst.description}
													</div>
												{/if}
											</div>

											{#if assistant.id === asst.id}
												<CheckCircleSolid size="md" class="text-blue-dark-40 group-hover:hidden" />
											{/if}
										</div>
									</DropdownItem>
								{/each}
							{/if}
						</Dropdown>
					{/if}
				</div>
				{#if assistant.interaction_mode === 'voice'}
					<div class="h-[5%] max-h-8"></div>
					{#if $isFirefox}
						<div class="rounded-lg bg-blue-light-50 p-3">
							<MicrophoneSlashOutline size="xl" class="text-blue-dark-40" />
						</div>
						<div class="flex w-3/5 flex-col items-center">
							<p class="text-center text-xl font-semibold text-blue-dark-40">
								Voice mode not available on Firefox
							</p>
							<p class="font-base text-center text-base text-gray-600">
								We're working on bringing Voice mode to Firefox in a future update. For the best
								experience, please use Safari, Chrome, or Edge in the meantime.
							</p>
						</div>
					{:else}
						<div class="rounded-lg bg-blue-light-50 p-3">
							<MicrophoneOutline size="xl" class="text-blue-dark-40" />
						</div>
						<div class="flex min-w-2/5 flex-col items-center">
							<p class="text-center text-sm font-semibold text-blue-dark-40 sm:text-xl">
								Voice mode
							</p>
							<p class="font-base text-center text-xs text-gray-600 sm:text-base">
								Talk to this assistant using your voice.<br />Create a new session to begin.
							</p>
						</div>
						<div class="flex flex-row p-1.5">
							<Button
								class="flex flex-row gap-1.5 rounded-lg bg-blue-dark-40 px-4 py-1.5 text-xs text-white transition-all hover:bg-blue-dark-50 hover:text-blue-light-50"
								onclick={handleAudioThreadCreate}
								ontouchstart={handleAudioThreadCreate}
								type="button"
							>
								<CirclePlusSolid size="sm" />
								<span class="text-center text-sm font-normal"> Create session </span>
							</Button>
						</div>
					{/if}
				{:else if assistant.interaction_mode === 'lecture_video'}
					<div class="h-[5%] max-h-8"></div>
					<div class="rounded-lg bg-blue-light-50 p-3">
						<ClapperboardPlayOutline size="xl" class="text-blue-dark-40" />
					</div>
					<div class="flex min-w-2/5 flex-col items-center">
						<p class="text-center text-sm font-semibold text-blue-dark-40 sm:text-xl">
							Lecture Video mode
						</p>
						<div class="my-2 flex items-center gap-2">
							<DropdownBadge
								extraClasses="border-red-400 from-red-100 to-red-200 px-2 py-0.5 text-base text-red-800"
								><span slot="name">In Development</span></DropdownBadge
							>
							<QuestionCircleOutline
								id="lecture-video-dev-tooltip-landing"
								class="h-5 w-5 cursor-help text-gray-600"
							/>
							<Tooltip
								triggeredBy="#lecture-video-dev-tooltip-landing"
								class="font-light"
								arrow={false}
								>Lecture Video mode is in active development and not fully functional.</Tooltip
							>
						</div>
						<p class="font-base text-center text-xs text-gray-600 sm:text-base">
							Review a lecture video with comprehension questions.<br />Create a new session to
							begin.
						</p>
						{#if assistant.lecture_video_key}
							<p class="mt-1 text-center text-xs text-gray-500">
								Video: {assistant.lecture_video_key}
							</p>
						{/if}
					</div>
					<div class="flex flex-row p-1.5">
						<Button
							class="flex flex-row gap-1.5 rounded-lg bg-blue-dark-40 px-4 py-1.5 text-xs text-white transition-all hover:bg-blue-dark-50 hover:text-blue-light-50"
							onclick={handleLectureThreadCreate}
							type="button"
						>
							<CirclePlusSolid size="sm" />
							<span class="text-center text-sm font-normal"> Create session </span>
						</Button>
					</div>
				{:else if assistant.interaction_mode === 'chat' && !(assistant.assistant_should_message_first ?? false)}
					<div class="h-[8%] max-h-16"></div>
					{#if !isPrivate && assistantMeta.willDisplayUserInfo}
						<div
							class="flex w-full flex-row items-stretch gap-2 rounded-2xl border border-red-600 px-3 py-1 transition-all duration-200 md:w-3/4 lg:w-3/5"
						>
							<UsersSolid size="sm" class="hidden pt-0 text-red-600 sm:inline" />
							<Span class="text-[0.7rem] font-normal text-gray-700 sm:text-xs"
								><Button
									class="p-0 text-[0.7rem] font-normal text-gray-700 underline sm:text-xs"
									onclick={showModeratorsModal}
									ontouchstart={showModeratorsModal}>Moderators</Button
								> have enabled a setting for this thread only that allows them to see
								<span class="font-semibold">your full name</span> and its content.</Span
							>
						</div>
					{/if}
					<div class="flex w-full flex-col items-center md:w-3/4 lg:w-3/5">
						<StatusErrors {assistantStatusUpdates} />
						{#key assistant.id}
							<ChatInput
								bind:this={chatInputRef}
								mimeType={data.uploadInfo.mimeType}
								maxSize={data.uploadInfo.private_file_max_size}
								loading={$loading || !!$navigating}
								canSubmit={true}
								visionAcceptedFiles={landingVisionAcceptedFiles}
								{visionSupportOverride}
								{useImageDescriptions}
								fileSearchAcceptedFiles={landingFileSearchAcceptedFiles}
								codeInterpreterAcceptedFiles={landingCodeInterpreterAcceptedFiles}
								upload={handleUpload}
								remove={handleRemove}
								on:submit={handleSubmit}
							/>
						{/key}
					</div>
				{:else if assistant.interaction_mode === 'chat' && (assistant.assistant_should_message_first ?? false)}
					<div class="h-[5%] max-h-8"></div>
					<div class="flex min-w-2/5 flex-col items-center">
						<p class="font-base text-center text-base text-gray-600">
							The assistant will send the first message.<br />Start a new conversation to begin.
						</p>
					</div>
					<div class="flex flex-row p-1.5">
						<Button
							class="flex flex-row gap-1.5 rounded-lg bg-blue-dark-40 px-4 py-1.5 text-xs text-white transition-all hover:bg-blue-dark-50 hover:text-blue-light-50"
							onclick={handleChatThreadCreate}
							ontouchstart={handleChatThreadCreate}
							type="button"
						>
							<PaperPlaneOutline size="sm" />
							<span class="text-center text-sm font-normal"> Start conversation </span>
						</Button>
					</div>
				{/if}
			</div>
			<div class="shrink-0 grow-0">
				<input type="hidden" name="assistant_id" value={assistant.id} />
				<input type="hidden" name="parties" value={parties} />
				<div class="my-3">
					{#if isPrivate}
						<div
							class="flex w-full flex-wrap items-start gap-2 text-[0.7rem] sm:text-xs lg:flex-nowrap"
						>
							<LockSolid size="sm" class="hidden pt-0 text-orange sm:block" />
							<Span class="font-normal text-gray-600"
								><Button
									class="p-0 text-[0.7rem] font-normal text-gray-600 underline sm:text-xs"
									onclick={showModeratorsModal}
									ontouchstart={showModeratorsModal}>Moderators</Button
								> <span class="font-semibold">cannot</span> see this thread or your name. For more
								information, please review
								<a href={resolve('/privacy-policy')} rel="noopener noreferrer" class="underline"
									>PingPong's privacy statement</a
								>. Assistants can make mistakes. Check important info.</Span
							>
						</div>
					{:else if assistantMeta.willDisplayUserInfo}
						{#if assistant.interaction_mode === 'voice'}
							<div
								class="flex w-full flex-wrap items-start gap-2 text-[0.7rem] sm:text-xs lg:flex-nowrap"
							>
								<UsersSolid size="sm" class="hidden pt-0 text-orange sm:block" />
								<Span class="font-normal text-gray-600"
									><Button
										class="p-0 text-[0.7rem] font-normal text-gray-600 underline sm:text-xs"
										onclick={showModeratorsModal}
										ontouchstart={showModeratorsModal}>Moderators</Button
									> can see this thread,
									<span class="font-semibold"
										>your full name, and listen to a recording of your conversation</span
									>. For more information, please review
									<a href={resolve('/privacy-policy')} rel="noopener noreferrer" class="underline"
										>PingPong's privacy statement</a
									>. Assistants can make mistakes. Check important info.</Span
								>
							</div>
						{:else}
							<div
								class="flex w-full flex-wrap items-start gap-2 text-[0.7rem] sm:text-xs lg:flex-nowrap"
							>
								<UsersSolid size="sm" class="hidden pt-0 text-orange sm:block" />
								<Span class="font-normal text-gray-600"
									><Button
										class="p-0 text-[0.7rem] font-normal text-gray-600 underline sm:text-xs"
										onclick={showModeratorsModal}
										ontouchstart={showModeratorsModal}>Moderators</Button
									> can see this thread and <span class="font-semibold">your full name</span>. For
									more information, please review
									<a href={resolve('/privacy-policy')} rel="noopener noreferrer" class="underline"
										>PingPong's privacy statement</a
									>. Assistants can make mistakes. Check important info.</Span
								>
							</div>
						{/if}
					{:else}
						<div
							class="flex w-full flex-wrap items-start gap-2 text-[0.7rem] sm:text-xs lg:flex-nowrap"
						>
							<EyeSlashOutline size="sm" class="hidden pt-0 text-orange sm:block" />
							<Span class="font-normal text-gray-600"
								><Button
									class="p-0 text-[0.7rem] font-normal text-gray-600 underline sm:text-xs"
									onclick={showModeratorsModal}
									ontouchstart={showModeratorsModal}>Moderators</Button
								> can see this thread but not your name. For more information, please review
								<a href={resolve('/privacy-policy')} rel="noopener noreferrer" class="underline"
									>PingPong's privacy statement</a
								>. Assistants can make mistakes. Check important info.</Span
							>
						</div>
					{/if}
				</div>
			</div>
		{:else}
			<div class="m-auto text-center">
				{#if !data.hasAssistants}
					<h1 class="text-2xl font-bold">No assistants configured.</h1>
				{:else if !data.hasAPIKey}
					<h1 class="text-2xl font-bold">No billing configured.</h1>
				{:else}
					<h1 class="text-2xl font-bold">Group is not configured.</h1>
				{/if}
			</div>
		{/if}
	</div>
	<ChatDropOverlay visible={dropOverlayVisible && canDropUploadsOnLanding} />
</div>
