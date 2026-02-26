<script lang="ts">
	import {
		Helper,
		Button,
		Checkbox,
		Label,
		Input,
		Heading,
		Textarea,
		Modal,
		type SelectOptionType,
		Badge,
		Accordion,
		AccordionItem,
		Range,
		ButtonGroup,
		RadioButton,
		InputAddon,
		Tooltip
	} from 'flowbite-svelte';
	import type { Tool, ServerFile, FileUploadInfo, MCPServerToolInput, MCPAuthType } from '$lib/api';
	import { beforeNavigate, goto, invalidate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import { setsEqual } from '$lib/set';
	import { happyToast, sadToast } from '$lib/toast';
	import { normalizeNewlines } from '$lib/content.js';
	import {
		CloseOutline,
		ImageOutline,
		QuestionCircleSolid,
		ArrowUpRightFromSquareOutline,
		CogOutline,
		LockSolid,
		BanOutline,
		FileImageOutline,
		ArrowLeftOutline,
		ArrowRightOutline,
		HeartSolid,
		LightbulbSolid,
		MessageDotsSolid,
		MessageDotsOutline,
		MicrophoneOutline,
		MicrophoneSolid,
		ArchiveOutline,
		FileVideoOutline,
		ClapperboardPlaySolid,
		ClapperboardPlayOutline
	} from 'flowbite-svelte-icons';
	import MultiSelectWithUpload from '$lib/components/MultiSelectWithUpload.svelte';
	import { writable, type Writable } from 'svelte/store';
	import { loading, loadingMessage } from '$lib/stores/general';
	import ModelDropdownOptions from '$lib/components/ModelDropdownOptions.svelte';
	import DropdownContainer from '$lib/components/DropdownContainer.svelte';
	import DropdownHeader from '$lib/components/DropdownHeader.svelte';
	import DropdownFooter from '$lib/components/DropdownFooter.svelte';
	import ConfirmationModal from '$lib/components/ConfirmationModal.svelte';
	import DropdownBadge from '$lib/components/DropdownBadge.svelte';
	import StatusErrors from '$lib/components/StatusErrors.svelte';
	import Sanitize from '$lib/components/Sanitize.svelte';
	import { page } from '$app/stores';
	import { computeLatestIncidentTimestamps, filterLatestIncidentUpdates } from '$lib/statusUpdates';
	import { tick } from 'svelte';
	import WebSourceChip from '$lib/components/WebSourceChip.svelte';
	import MCPServerModal from '$lib/components/MCPServerModal.svelte';
	export let data;
	const LECTURE_VIDEO_DEFAULT_INSTRUCTIONS = 'You are a lecture video assistant.';

	// Flag indicating whether we should check for changes before navigating away.
	let checkForChanges = true;
	let advancedOptionsOpen = false;
	let assistantForm: HTMLFormElement;
	let deleteModal = false;
	$: assistant = data.assistant;
	$: preventEdits = !!assistant?.locked;
	$: canPublish = data.grants.canPublishAssistants;
	$: isClassPrivate = data.class?.private || false;

	let assistantName = '';
	let hasSetAssistantName = false;
	$: if (assistant?.name !== undefined && assistant?.name !== null && !hasSetAssistantName) {
		assistantName = assistant.name;
		hasSetAssistantName = true;
	}
	let interactionMode: 'chat' | 'voice' | 'lecture_video';
	$: if (
		assistant?.interaction_mode !== undefined &&
		assistant?.interaction_mode !== null &&
		interactionMode === undefined
	) {
		interactionMode = assistant.interaction_mode;
	}
	$: if (
		interactionMode === undefined &&
		(data.isCreating ||
			assistant?.interaction_mode === undefined ||
			assistant?.interaction_mode === null)
	) {
		interactionMode = 'chat';
	}
	$: isLectureMode = interactionMode === 'lecture_video';
	$: isEditingLectureAssistant =
		!data.isCreating && (assistant?.interaction_mode || null) === 'lecture_video';
	$: showLectureModeOption =
		(data.isCreating && data.isInstitutionAdmin) || isEditingLectureAssistant;
	$: modelInteractionMode = isLectureMode ? 'chat' : interactionMode;
	let description = '';
	let hasSetDescription = false;
	$: if (
		assistant?.description !== undefined &&
		assistant?.description !== null &&
		!hasSetDescription
	) {
		description = assistant.description;
		hasSetDescription = true;
	}
	let instructions = '';
	let hasSetInstructions = false;
	$: if (
		assistant?.instructions !== undefined &&
		assistant?.instructions !== null &&
		!hasSetInstructions
	) {
		instructions = assistant.instructions;
		hasSetInstructions = true;
	}
	let notes = '';
	let hasSetNotes = false;
	$: if (assistant?.notes !== undefined && assistant?.notes !== null && !hasSetNotes) {
		notes = assistant.notes;
		hasSetNotes = true;
	}
	let currentLectureVideoKey = '';
	$: currentLectureVideoKey = assistant?.lecture_video_key || '';
	let lectureVideoKey = '';
	let hasSetLectureVideoKey = false;
	$: if (!hasSetLectureVideoKey) {
		if (!data.isCreating && assistant?.lecture_video_key) {
			lectureVideoKey = assistant.lecture_video_key;
		} else {
			lectureVideoKey = $page.url.searchParams.get('lecture_video_key') || '';
		}
		hasSetLectureVideoKey = true;
	}
	let hidePrompt = data.isCreating;
	let hasSetHidePrompt = false;
	$: if (
		assistant?.hide_prompt !== undefined &&
		assistant?.hide_prompt !== null &&
		!hasSetHidePrompt
	) {
		hidePrompt = assistant?.hide_prompt;
		hasSetHidePrompt = true;
	}
	let useLatex = data.isCreating;
	let hasSetUseLatex = false;
	$: if (assistant?.use_latex !== undefined && assistant?.use_latex !== null && !hasSetUseLatex) {
		useLatex = assistant?.use_latex;
		hasSetUseLatex = true;
	}
	let mcpServersLocal: MCPServerToolInput[] = [];
	$: mcpServersFromRequest = data.mcpServers.slice();
	let hasSetMCPServers = false;
	$: if (data.mcpServers !== undefined && data.mcpServers !== null && !hasSetMCPServers) {
		mcpServersLocal = data.mcpServers.slice();
		hasSetMCPServers = true;
	}
	let showMCPServerModal = false;
	let mcpServerEditIndex: number | null = null;

	$: mcpServerEditFromServer =
		mcpServerEditIndex !== null ? mcpServersFromRequest[mcpServerEditIndex] : null;
	$: mcpServerEdit = mcpServerEditIndex !== null ? mcpServersLocal[mcpServerEditIndex] : null;

	const saveMCPServerAndCloseModal = (server: MCPServerToolInput, index: number | null) => {
		if (!server) {
			sadToast('Error: MCP Server data is missing.');
			return;
		}
		if (index !== null) {
			mcpServersLocal[index] = server;
		} else {
			mcpServersLocal = [...mcpServersLocal, server];
		}
		mcpServerEditIndex = null;
		showMCPServerModal = false;
	};

	const resetDraftMCPServerAndCloseModal = () => {
		mcpServerEditIndex = null;
		showMCPServerModal = false;
	};

	const removeServer = (index: number) => {
		mcpServersLocal = mcpServersLocal.filter((_, i) => i !== index);
	};

	let selectedFileSearchFiles = writable(
		data.selectedFileSearchFiles.slice().map((f) => f.file_id)
	);
	let selectedCodeInterpreterFiles = writable(
		data.selectedCodeInterpreterFiles.slice().map((f) => f.file_id)
	);

	// The list of adhoc files being uploaded.
	let privateUploadFSFileInfo = writable<FileUploadInfo[]>([]);
	let privateUploadCIFileInfo = writable<FileUploadInfo[]>([]);
	const trashPrivateFileIds = writable<number[]>([]);
	$: uploadingFSPrivate = $privateUploadFSFileInfo.some((f) => f.state === 'pending');
	$: uploadingCIPrivate = $privateUploadCIFileInfo.some((f) => f.state === 'pending');
	$: privateFSSessionFiles = $privateUploadFSFileInfo
		.filter((f) => f.state === 'success')
		.map((f) => f.response as ServerFile);
	$: privateCISessionFiles = $privateUploadCIFileInfo
		.filter((f) => f.state === 'success')
		.map((f) => f.response as ServerFile);
	$: allFSPrivateFiles = [
		...data.selectedFileSearchFiles.slice().filter((f) => f.private),
		...privateFSSessionFiles
	];
	$: allCIPrivateFiles = [
		...data.selectedCodeInterpreterFiles.slice().filter((f) => f.private),
		...privateCISessionFiles
	];

	const fileSearchMetadata = {
		value: 'file_search',
		name: 'File Search',
		description:
			'File Search augments the Assistant with knowledge from outside its model using documents you provide.',
		max_count: 100
	};
	const codeInterpreterMetadata = {
		value: 'code_interpreter',
		name: 'Code Interpreter',
		description:
			'Code Interpreter can process files with diverse data and formatting, and generate files with data and images of graphs. Code Interpreter allows your Assistant to run code iteratively to solve challenging code and math problems.',
		max_count: 20
	};
	const webSearchMetadata = {
		value: 'web_search',
		name: 'Web Search',
		description:
			'Web search allows models to access up-to-date information from the internet and provide answers with sourced citations.'
	};
	const mcpServerMetadata = {
		value: 'mcp_server',
		name: 'MCP Servers',
		description:
			'Use remote MCP servers to give models new capabilities. MCP Server support is currently in preview and may be unstable. Do not use for important tasks. Make sure you trust the MCP server you are connecting to.'
	};
	const defaultTools = [{ type: 'file_search' }];
	const mcpAuthTypeLabels: Record<MCPAuthType, string> = {
		token: 'Access token/API key',
		header: 'Custom headers',
		none: 'None'
	};

	const normalizeMcpServersForCompare = (servers: MCPServerToolInput[]) =>
		servers
			.map((server) => ({
				server_label: server.server_label ?? '',
				server_url: server.server_url ?? '',
				display_name: server.display_name ?? '',
				auth_type: server.auth_type ?? 'none',
				authorization_token: server.authorization_token ?? '',
				description: server.description ?? '',
				enabled: server.enabled ?? true,
				headers: server.headers
					? Object.entries(server.headers)
							.map(([key, value]) => [key, value])
							.sort(([a], [b]) => a.localeCompare(b))
					: []
			}))
			.sort((a, b) => {
				const labelCompare = a.server_label.localeCompare(b.server_label);
				if (labelCompare !== 0) {
					return labelCompare;
				}
				return a.server_url.localeCompare(b.server_url);
			});

	const areMcpServersEqual = (left: MCPServerToolInput[], right: MCPServerToolInput[]) =>
		JSON.stringify(normalizeMcpServersForCompare(left)) ===
		JSON.stringify(normalizeMcpServersForCompare(right));

	const cleanMcpServerForRequest = (server: MCPServerToolInput): MCPServerToolInput => {
		const cleaned: MCPServerToolInput = {
			server_label: server.server_label?.trim() || undefined,
			display_name: server.display_name.trim(),
			server_url: server.server_url.trim(),
			auth_type: server.auth_type,
			description: server.description?.trim() || undefined,
			enabled: server.enabled ?? true
		};

		if (server.auth_type === 'token' && server.authorization_token) {
			cleaned.authorization_token = server.authorization_token;
		}
		if (server.auth_type === 'header' && server.headers && Object.keys(server.headers).length) {
			cleaned.headers = server.headers;
		}

		return cleaned;
	};

	let createClassicAssistantByProviderOrUser = false;
	let hasSetCreateClassicAssistant = false;
	$: if (
		data?.enforceClassicAssistants !== undefined &&
		data?.enforceClassicAssistants !== null &&
		!hasSetCreateClassicAssistant
	) {
		createClassicAssistantByProviderOrUser = data?.enforceClassicAssistants;
		hasSetCreateClassicAssistant = true;
	}
	$: createClassicAssistant = isLectureMode
		? false
		: createClassicAssistantByProviderOrUser || interactionMode === 'voice';
	$: isClassicRequired = isLectureMode
		? false
		: data?.enforceClassicAssistants || interactionMode === 'voice';

	$: chatModelCount = data.models.filter((model) => model.type === 'chat').length;
	$: audioModelCount = data.models.filter((model) => model.type === 'voice').length;

	$: initialTools = (assistant?.tools ? (JSON.parse(assistant.tools) as Tool[]) : defaultTools).map(
		(t) => t.type
	);
	$: modelNameDict = data.models.reduce<{ [key: string]: string }>((acc, model) => {
		acc[model.id] = model.name + (model.is_latest ? ' (Latest)' : ' (Pinned Version)');
		return acc;
	}, {});
	let forcedAssistantVersion: number | null = null;
	$: assistantVersion = forcedAssistantVersion || assistant?.version || null;
	let convertToNextGen: boolean | null = null;
	$: canSwitchAssistantVersion =
		!data.isCreating &&
		interactionMode === 'voice' &&
		!data?.enforceClassicAssistants &&
		!isLectureMode;
	$: if (convertToNextGen !== null && !canSwitchAssistantVersion) {
		convertToNextGen = null;
		forcedAssistantVersion = null;
	}
	$: if (data.isCreating && isLectureMode) {
		forcedAssistantVersion = 3;
		convertToNextGen = null;
	}
	$: statusComponents = (data.statusComponents || {}) as Partial<
		Record<string, api.StatusComponentUpdate[]>
	>;
	let latestIncidentUpdateTimestamps: Record<string, number> = {};
	$: latestIncidentUpdateTimestamps = computeLatestIncidentTimestamps(statusComponents);
	$: statusComponentId = data.isCreating
		? createClassicAssistant
			? api.STATUS_COMPONENT_IDS.classic
			: api.STATUS_COMPONENT_IDS.nextGen
		: assistantVersion === 3
			? api.STATUS_COMPONENT_IDS.nextGen
			: api.STATUS_COMPONENT_IDS.classic;
	$: assistantStatusUpdates = filterLatestIncidentUpdates(
		statusComponents[statusComponentId],
		latestIncidentUpdateTimestamps
	);
	$: latestModelOptions = (
		data.models.filter(
			(model) =>
				model.is_latest &&
				!(model.hide_in_model_selector ?? false) &&
				((data.isCreating && createClassicAssistant) || (!data.isCreating && assistantVersion !== 3)
					? model.supports_classic_assistants
					: model.supports_next_gen_assistants) &&
				model.type === modelInteractionMode
		) || []
	).map((model) => ({
		value: model.id,
		name: model.name,
		description: model.description,
		supports_vision:
			model.supports_vision &&
			(model.vision_support_override === undefined || model.vision_support_override),
		supports_reasoning: model.supports_reasoning,
		is_new: model.is_new,
		highlight: model.highlight
	}));
	$: hiddenModelNames = (
		data.models.filter(
			(model) => (model.hide_in_model_selector ?? false) && model.type === modelInteractionMode
		) || []
	).map((model) => model.id);
	let selectedModel = '';
	$: if (
		((latestModelOptions.length > 0 || versionedModelOptions.length > 0) && !selectedModel) ||
		(!latestModelOptions.map((m) => m.value).includes(selectedModel) &&
			!versionedModelOptions.map((m) => m.value).includes(selectedModel))
	) {
		if (
			latestModelOptions.map((m) => m.value).includes(assistant?.model || '') ||
			hiddenModelNames.includes(assistant?.model || '')
		) {
			selectedModel = assistant?.model || latestModelOptions[0].value;
		} else if (
			versionedModelOptions.map((m) => m.value).includes(assistant?.model || '') ||
			hiddenModelNames.includes(assistant?.model || '')
		) {
			selectedModel = assistant?.model || versionedModelOptions[0].value;
		} else if (latestModelOptions.length > 0) {
			const highlighted = latestModelOptions.find((m) => m.highlight);
			selectedModel = highlighted ? highlighted.value : latestModelOptions[0].value;
		} else if (versionedModelOptions.length > 0) {
			const highlighted = versionedModelOptions.find((m) => m.highlight);
			selectedModel = highlighted ? highlighted.value : versionedModelOptions[0].value;
		} else {
			selectedModel = '';
		}
	}
	$: if (isLectureMode && data.isCreating && latestModelOptions.length > 0) {
		selectedModel = latestModelOptions[0].value;
	}
	$: if (isLectureMode && !data.isCreating && assistant?.model) {
		selectedModel = assistant.model;
	}
	$: selectedModelName = modelNameDict[selectedModel];
	let selectedModelRecord: api.AssistantModel | undefined;
	$: selectedModelRecord = data.models.find((model) => model.id === selectedModel);
	$: versionedModelOptions = (
		data.models.filter(
			(model) =>
				!model.is_latest &&
				!(model.hide_in_model_selector ?? false) &&
				((data.isCreating && createClassicAssistant) || (!data.isCreating && assistantVersion !== 3)
					? model.supports_classic_assistants
					: model.supports_next_gen_assistants) &&
				model.type === modelInteractionMode
		) || []
	).map((model) => ({
		value: model.id,
		name: model.name,
		description: model.description,
		supports_vision:
			model.supports_vision &&
			(model.vision_support_override === undefined || model.vision_support_override),
		supports_reasoning: model.supports_reasoning,
		is_new: model.is_new,
		highlight: model.highlight
	}));
	let availableModelIds: string[] = [];
	let selectedModelDeprecated = false;
	$: availableModelIds = [...latestModelOptions, ...versionedModelOptions].map(
		(model) => model.value
	);
	$: selectedModelDeprecated = !!selectedModel && !availableModelIds.includes(selectedModel);
	$: supportVisionModels = (data.models.filter((model) => model.supports_vision) || []).map(
		(model) => model.id
	);
	$: supportFileSearchModels = (
		data.models.filter((model) => model.supports_file_search) || []
	).map((model) => model.id);
	$: supportsFileSearch = supportFileSearchModels.includes(selectedModel);
	$: supportCodeInterpreterModels = (
		data.models.filter((model) => model.supports_code_interpreter) || []
	).map((model) => model.id);
	$: supportsCodeInterpreter = supportCodeInterpreterModels.includes(selectedModel);
	$: supportTemperatureModels = (
		data.models.filter((model) => model.supports_temperature) || []
	).map((model) => model.id);
	$: supportsTemperature = supportTemperatureModels.includes(selectedModel);
	$: supportReasoningModels = (data.models.filter((model) => model.supports_reasoning) || []).map(
		(model) => model.id
	);
	$: supportMinimalReasoningEffortModels = (
		data.models.filter((model) => model.supports_minimal_reasoning_effort) || []
	).map((model) => model.id);
	$: supportNoneReasoningEffortModels = (
		data.models.filter((model) => model.supports_none_reasoning_effort) || []
	).map((model) => model.id);
	$: supportsReasoning = supportReasoningModels.includes(selectedModel);
	$: supportsMinimalReasoningEffort = supportMinimalReasoningEffortModels.includes(selectedModel);
	$: supportsNoneReasoningEffort = supportNoneReasoningEffortModels.includes(selectedModel);
	$: supportsVerbosityModels = (data.models.filter((model) => model.supports_verbosity) || []).map(
		(model) => model.id
	);
	$: supportsVerbosity = supportsVerbosityModels.includes(selectedModel);
	$: supportsWebSearchModels = (data.models.filter((model) => model.supports_web_search) || []).map(
		(model) => model.id
	);
	$: supportsWebSearch = supportsWebSearchModels.includes(selectedModel);
	$: supportsMCPServerModels = (data.models.filter((model) => model.supports_mcp_server) || []).map(
		(model) => model.id
	);
	$: supportsMCPServer = supportsMCPServerModels.includes(selectedModel);
	$: supportsVision = supportVisionModels.includes(selectedModel);
	$: visionSupportOverride = data.models.find(
		(model) => model.id === selectedModel
	)?.vision_support_override;
	$: finalVisionSupport = visionSupportOverride ?? supportsVision;
	let allowVisionUpload = true;
	$: asstFSFiles = [...data.files, ...allFSPrivateFiles];
	$: asstCIFiles = [...data.files, ...allCIPrivateFiles];

	let fileSearchOptions: SelectOptionType<string>[] = [];
	let codeInterpreterOptions: SelectOptionType<string>[] = [];
	const fileSearchFilter = data.uploadInfo.getFileSupportFilter({
		code_interpreter: false,
		file_search: true,
		vision: false
	});
	const codeInterpreterFilter = data.uploadInfo.getFileSupportFilter({
		code_interpreter: true,
		file_search: false,
		vision: false
	});
	$: fileSearchOptions = (asstFSFiles || [])
		.filter(fileSearchFilter)
		.map((file) => ({ value: file.file_id, name: file.name }));
	$: codeInterpreterOptions = (asstCIFiles || [])
		.filter(codeInterpreterFilter)
		.map((file) => ({ value: file.file_id, name: file.name }));

	let fileSearchToolSelect = false;
	let hasSetFileSearchToolSelect = false;
	$: if (initialTools !== undefined && initialTools !== null && !hasSetFileSearchToolSelect) {
		fileSearchToolSelect = initialTools.includes('file_search');
		hasSetFileSearchToolSelect = true;
	}
	let codeInterpreterToolSelect = false;
	let hasSetCodeInterpreterToolSelect = false;
	$: if (initialTools !== undefined && initialTools !== null && !hasSetCodeInterpreterToolSelect) {
		codeInterpreterToolSelect = initialTools.includes('code_interpreter');
		hasSetCodeInterpreterToolSelect = true;
	}
	let webSearchToolSelect = false;
	let hasSetWebSearchToolSelect = false;
	$: if (initialTools !== undefined && initialTools !== null && !hasSetWebSearchToolSelect) {
		webSearchToolSelect = initialTools.includes('web_search');
		hasSetWebSearchToolSelect = true;
	}
	let mcpServerToolSelect = false;
	let hasSetMCPServerToolSelect = false;
	$: if (initialTools !== undefined && initialTools !== null && !hasSetMCPServerToolSelect) {
		mcpServerToolSelect = initialTools.includes('mcp_server');
		hasSetMCPServerToolSelect = true;
	}
	let isPublished = false;
	let hasSetIsPublished = false;
	$: if (
		assistant?.published !== undefined &&
		assistant?.published !== null &&
		!hasSetIsPublished
	) {
		isPublished = !!assistant?.published;
		hasSetIsPublished = true;
	}
	let useImageDescriptions = false;
	let hasSetImageDescriptions = false;
	$: if (
		assistant?.use_image_descriptions !== undefined &&
		assistant?.use_image_descriptions !== null &&
		!hasSetImageDescriptions
	) {
		useImageDescriptions = assistant?.use_image_descriptions;
		hasSetImageDescriptions = true;
	}
	let assistantShouldMessageFirst = false;
	let hasSetAssistantShouldMessageFirst = false;
	$: if (
		assistant?.assistant_should_message_first !== undefined &&
		assistant?.assistant_should_message_first !== null &&
		!hasSetAssistantShouldMessageFirst
	) {
		assistantShouldMessageFirst = assistant?.assistant_should_message_first;
		hasSetAssistantShouldMessageFirst = true;
	}

	let shouldRecordNameOrVoice = false;
	let hasSetShouldRecordNameOrVoice = false;
	$: if (
		assistant?.should_record_user_information !== undefined &&
		assistant?.should_record_user_information !== null &&
		!hasSetShouldRecordNameOrVoice
	) {
		shouldRecordNameOrVoice = assistant?.should_record_user_information;
		hasSetShouldRecordNameOrVoice = true;
	}

	let allowUserFileUploads = true;
	let hasSetAllowUserFileUploads = false;
	$: if (
		assistant?.allow_user_file_uploads !== undefined &&
		assistant?.allow_user_file_uploads !== null &&
		!hasSetAllowUserFileUploads
	) {
		allowUserFileUploads = assistant?.allow_user_file_uploads;
		hasSetAllowUserFileUploads = true;
	}

	let allowUserImageUploads = true;
	let hasSetAllowUserImageUploads = false;
	$: if (
		assistant?.allow_user_image_uploads !== undefined &&
		assistant?.allow_user_image_uploads !== null &&
		!hasSetAllowUserImageUploads
	) {
		allowUserImageUploads = assistant?.allow_user_image_uploads;
		hasSetAllowUserImageUploads = true;
	}

	let hideReasoningSummaries = true;
	let hasSetHideReasoningSummaries = false;
	$: if (
		assistant?.hide_reasoning_summaries !== undefined &&
		assistant?.hide_reasoning_summaries !== null &&
		!hasSetHideReasoningSummaries
	) {
		hideReasoningSummaries = assistant?.hide_reasoning_summaries;
		hasSetHideReasoningSummaries = true;
	}

	let hideFileSearchResultQuotes = true;
	let hasSetHideFileSearchResultQuotes = false;
	$: if (
		assistant?.hide_file_search_result_quotes !== undefined &&
		assistant?.hide_file_search_result_quotes !== null &&
		!hasSetHideFileSearchResultQuotes
	) {
		hideFileSearchResultQuotes = assistant?.hide_file_search_result_quotes;
		if (hideFileSearchResultQuotes) {
			hideFileSearchDocumentNames = true;
		}
		hasSetHideFileSearchResultQuotes = true;
	}

	let hideFileSearchDocumentNames = false;
	let hasSetHideFileSearchDocumentNames = false;
	$: if (
		assistant?.hide_file_search_document_names !== undefined &&
		assistant?.hide_file_search_document_names !== null &&
		!hasSetHideFileSearchDocumentNames
	) {
		hideFileSearchDocumentNames = assistant?.hide_file_search_document_names;
		hasSetHideFileSearchDocumentNames = true;
	}

	let hideFileSearchQueries = true;
	let hasSetHideFileSearchQueries = false;
	$: if (
		assistant?.hide_file_search_queries !== undefined &&
		assistant?.hide_file_search_queries !== null &&
		!hasSetHideFileSearchQueries
	) {
		hideFileSearchQueries = assistant?.hide_file_search_queries;
		hasSetHideFileSearchQueries = true;
	}
	$: if (hideFileSearchDocumentNames) {
		hideFileSearchResultQuotes = true;
	}

	let hasSetHideMCPServerCallDetails = false;
	let hideMCPServerCallDetails = true;
	$: if (
		assistant?.hide_mcp_server_call_details !== undefined &&
		assistant?.hide_mcp_server_call_details !== null &&
		!hasSetHideMCPServerCallDetails
	) {
		hideMCPServerCallDetails = assistant?.hide_mcp_server_call_details;
		hasSetHideMCPServerCallDetails = true;
	}

	let hideWebSearchSources = false;
	let hasSetHideWebSearchSources = false;
	$: if (
		assistant?.hide_web_search_sources !== undefined &&
		assistant?.hide_web_search_sources !== null &&
		!hasSetHideWebSearchSources
	) {
		hideWebSearchSources = assistant?.hide_web_search_sources;
		hasSetHideWebSearchSources = true;
	}

	let hideWebSearchActions = false;
	let hasSetHideWebSearchActions = false;
	$: if (
		assistant?.hide_web_search_actions !== undefined &&
		assistant?.hide_web_search_actions !== null &&
		!hasSetHideWebSearchActions
	) {
		hideWebSearchActions = assistant?.hide_web_search_actions;
		if (hideWebSearchActions) {
			hideWebSearchSources = true;
		}
		hasSetHideWebSearchActions = true;
	}

	$: if (hideWebSearchActions) {
		hideWebSearchSources = true;
	}

	// Handle updates from the file upload component.
	const handleFSPrivateFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
		privateUploadFSFileInfo = e.detail;
	};
	const handleCIPrivateFilesChange = (e: CustomEvent<Writable<FileUploadInfo[]>>) => {
		privateUploadCIFileInfo = e.detail;
	};

	// Handle file deletion.
	const removePrivateFiles = async (evt: CustomEvent<Array<number>>) => {
		const files = evt.detail;
		$trashPrivateFileIds = [...$trashPrivateFileIds, ...files];
	};

	let defaultAudioTemperature = 0.8;
	let defaultChatTemperature = 0.2;
	let minChatTemperature = 0.0;
	let maxChatTemperature = 2.0;
	let minAudioTemperature = 0.6;
	let maxAudioTemperature = 1.2;

	const checkForLargeTemperatureChat = (evt: Event) => {
		const target = evt.target as HTMLInputElement;
		const value = target.valueAsNumber;
		if (value > 1.0 && _temperatureValue <= 1.0) {
			if (confirm('Temperatures above 1.0 may lead to nonsensical responses. Are you sure?')) {
				temperatureValue = value;
				_temperatureValue = value;
			} else {
				target.valueAsNumber = _temperatureValue;
				temperatureValue = _temperatureValue;
			}
		} else {
			temperatureValue = value;
			_temperatureValue = value;
		}
	};

	const checkForLargeTemperatureAudio = (evt: Event) => {
		const target = evt.target as HTMLInputElement;
		const value = target.valueAsNumber;
		if (value !== defaultAudioTemperature && _temperatureValue === defaultAudioTemperature) {
			if (
				confirm(
					'For audio models, a temperature of 0.8 is highly recommended for best performance. Are you sure?'
				)
			) {
				temperatureValue = value;
				_temperatureValue = value;
			} else {
				target.valueAsNumber = _temperatureValue;
				temperatureValue = _temperatureValue;
			}
		} else {
			temperatureValue = value;
			_temperatureValue = value;
		}
	};

	let temperatureValue: number;
	let _temperatureValue: number;
	$: if (
		assistant?.temperature !== undefined &&
		assistant?.temperature !== null &&
		temperatureValue === undefined
	) {
		temperatureValue = assistant.temperature;
		_temperatureValue = assistant.temperature;
	}

	const setDefaultModelPrompt = (model: string) => {
		const matchingModels = data.models.filter((m) => m.id === model);
		let found = false;
		matchingModels.forEach((m) => {
			if (m.default_prompt_id) {
				instructions = data.defaultPrompts.find((p) => p.id === m.default_prompt_id)?.prompt || '';
				hasSetInstructions = true;
				found = true;
			}
		});
		if (!found) {
			instructions = '';
			hasSetInstructions = true;
		}
	};

	const changeInteractionMode = async (evt: Event) => {
		const target = evt.target as HTMLInputElement;
		const mode = target.value as 'chat' | 'voice' | 'lecture_video';
		if (mode === 'voice') {
			forcedAssistantVersion = 2;
		} else if (mode === 'lecture_video') {
			forcedAssistantVersion = 3;
			convertToNextGen = null;
		} else {
			forcedAssistantVersion = null;
		}
		if (
			assistant?.interaction_mode === mode &&
			assistant?.temperature !== undefined &&
			assistant?.temperature !== null
		) {
			temperatureValue = assistant.temperature;
			_temperatureValue = assistant.temperature;
		} else if (mode === 'voice') {
			temperatureValue = defaultAudioTemperature;
			_temperatureValue = defaultAudioTemperature;
		} else if (mode === 'chat' || mode === 'lecture_video') {
			temperatureValue = defaultChatTemperature;
			_temperatureValue = defaultChatTemperature;
		}
		if (
			assistant?.interaction_mode === mode &&
			assistant?.instructions !== undefined &&
			assistant?.instructions !== null
		) {
			instructions = assistant.instructions;
			hasSetInstructions = true;
		} else {
			await tick();
			setDefaultModelPrompt(selectedModel);
		}
	};
	let reasoningEffortValue: number;
	let reasoningEffortLevels: number[] = [];
	let reasoningEffortMin = -1;
	let reasoningEffortMax = 2;
	let reasoningEffortLabels: string[] = [];
	let defaultReasoningLabel = 'low';
	$: if (
		assistant?.reasoning_effort !== undefined &&
		assistant?.reasoning_effort !== null &&
		reasoningEffortValue === undefined
	) {
		reasoningEffortValue = assistant.reasoning_effort;
	}
	$: if (
		temperatureValue === undefined &&
		(data.isCreating || assistant?.temperature === undefined || assistant?.temperature === null)
	) {
		if (interactionMode === 'voice') {
			temperatureValue = defaultAudioTemperature;
			_temperatureValue = defaultAudioTemperature;
		} else if (interactionMode === 'chat' || interactionMode === 'lecture_video') {
			temperatureValue = defaultChatTemperature;
			_temperatureValue = defaultChatTemperature;
		}
	}
	$: if (
		reasoningEffortValue === undefined &&
		(data.isCreating ||
			assistant?.reasoning_effort === undefined ||
			assistant?.reasoning_effort === null)
	) {
		reasoningEffortValue = 0;
	}
	const getReasoningEffortLabel = (level: number) => {
		switch (level) {
			case -1:
				return supportsNoneReasoningEffort ? 'none' : 'minimal';
			case 0:
				return 'low';
			case 1:
				return 'medium';
			case 2:
				return 'high';
			default:
				return '';
		}
	};
	$: reasoningEffortLevels =
		selectedModelRecord?.reasoning_effort_levels ??
		(supportsNoneReasoningEffort || supportsMinimalReasoningEffort ? [-1, 0, 1, 2] : [0, 1, 2]);
	$: reasoningEffortMin = reasoningEffortLevels.length ? Math.min(...reasoningEffortLevels) : 0;
	$: reasoningEffortMax = reasoningEffortLevels.length ? Math.max(...reasoningEffortLevels) : 2;
	$: reasoningEffortLabels = reasoningEffortLevels
		.map(getReasoningEffortLabel)
		.filter((label) => label);
	$: defaultReasoningLabel = reasoningEffortLevels.includes(0)
		? getReasoningEffortLabel(0)
		: getReasoningEffortLabel(reasoningEffortLevels[0] ?? 0);
	$: if (
		supportsReasoning &&
		reasoningEffortLevels.length > 0 &&
		!reasoningEffortLevels.includes(reasoningEffortValue)
	) {
		reasoningEffortValue = reasoningEffortLevels[0];
	}
	let verbosityValue: number;
	$: if (
		assistant?.verbosity !== undefined &&
		assistant?.verbosity !== null &&
		verbosityValue === undefined
	) {
		verbosityValue = assistant.verbosity;
	}
	$: if (
		verbosityValue === undefined &&
		(data.isCreating || assistant?.verbosity === undefined || assistant?.verbosity === null)
	) {
		verbosityValue = 1;
	}

	let dropdownOpen = false;
	/**
	 * Check if the assistant model supports vision capabilities.
	 */
	const updateSelectedModel = (modelValue: string) => {
		dropdownOpen = false;
		selectedModel = modelValue;
	};

	let modelNodes: { [key: string]: HTMLElement } = {};
	let modelHeaders: { [key: string]: string } = {};

	/**
	 * Determine if a specific field has changed in the form.
	 */
	const checkDirtyField = (
		field: keyof api.CreateAssistantRequest & keyof api.Assistant,
		update: api.CreateAssistantRequest,
		original: api.Assistant | null
	) => {
		const newValue = update[field];
		const oldValue = original?.[field];

		let dirty = true;

		switch (field) {
			case 'name':
				dirty = newValue !== (oldValue || '');
				break;
			case 'description':
				dirty =
					normalizeNewlines((newValue as string | undefined) || '') !==
					normalizeNewlines((oldValue as string) || '');
				break;
			case 'notes':
				dirty =
					normalizeNewlines((newValue as string | undefined) || '') !==
					((oldValue as string) || '');
				break;
			case 'instructions':
				dirty =
					normalizeNewlines((newValue as string | undefined) || '') !==
					((oldValue as string) || '');
				break;
			case 'model':
				dirty = newValue !== oldValue;
				break;
			case 'temperature':
				dirty = newValue !== oldValue;
				break;
			case 'reasoning_effort':
				dirty = newValue !== oldValue;
				break;
			case 'published':
				dirty = newValue === undefined ? false : newValue !== !!oldValue;
				break;
			case 'use_latex':
				dirty =
					newValue === undefined
						? false
						: (preventEdits ? !!assistant?.use_latex : newValue) !== oldValue;
				break;
			case 'use_image_descriptions':
				dirty = newValue === undefined ? false : newValue !== !!oldValue;
				break;
			case 'hide_prompt':
				dirty =
					newValue === undefined
						? false
						: (preventEdits ? !!assistant?.hide_prompt : newValue) !== oldValue;
				break;
			case 'tools':
				dirty = !setsEqual(
					new Set((newValue as api.Tool[]).map((t) => t.type)),
					new Set(initialTools)
				);
				break;
			default:
				dirty = newValue !== oldValue;
		}

		if (dirty) {
			return true;
		}

		return false;
	};

	/**
	 * Check if the form has substantively changed.
	 */
	const findAllDirtyFields = (params: api.CreateAssistantRequest) => {
		// Check if the new params are different from the loaded assistant.
		// If the assistant is brand new, ignore simple checkboxes and dropdowns,
		// and only check text entry fields.
		const fields: Array<keyof api.CreateAssistantRequest & keyof api.Assistant> = data.assistantId
			? [
					'name',
					'description',
					'instructions',
					'notes',
					'interaction_mode',
					'model',
					'published',
					'use_latex',
					'use_image_descriptions',
					'hide_prompt',
					'tools',
					'temperature',
					'reasoning_effort'
				]
			: isLectureMode
				? ['name', 'description']
				: ['name', 'description', 'instructions'];

		const modifiedFields: string[] = [];
		for (const field of fields) {
			if (checkDirtyField(field, params, assistant)) {
				modifiedFields.push(field);
			}
		}

		// Check selected files separately since these are handled differently in the form.
		if (
			!setsEqual(
				new Set($selectedCodeInterpreterFiles),
				new Set(data.selectedCodeInterpreterFiles.map((f) => f.file_id))
			)
		) {
			modifiedFields.push('code interpreter files');
		}
		if (
			!setsEqual(
				new Set($selectedFileSearchFiles),
				new Set(data.selectedFileSearchFiles.map((f) => f.file_id))
			)
		) {
			modifiedFields.push('file search files');
		}
		if (!areMcpServersEqual(mcpServersLocal, data.mcpServers || [])) {
			modifiedFields.push('mcp servers');
		}
		if (convertToNextGen !== null) {
			modifiedFields.push('assistant version');
		}
		const newLectureVideoKey = (params.lecture_video_key || '').trim();
		if (newLectureVideoKey.length > 0 && newLectureVideoKey !== currentLectureVideoKey) {
			modifiedFields.push('lecture video key');
		}

		return modifiedFields;
	};

	/**
	 * Parse data from the assistants form into API request params.
	 */
	const parseFormData = (
		form: HTMLFormElement
	): api.CreateAssistantRequest & { convert_to_next_gen?: boolean } => {
		const formData = new FormData(form);
		const body = Object.fromEntries(formData.entries());
		const includeTooling = !isLectureMode;
		const lectureVideoKeyValue = lectureVideoKey.trim();
		const lectureModeInstructions = normalizeNewlines(
			(assistant?.instructions || LECTURE_VIDEO_DEFAULT_INSTRUCTIONS).trim()
		);

		const tools: api.Tool[] = [];
		const fileSearchCodeInterpreterUnusedFiles: number[] = [];
		if (
			includeTooling &&
			fileSearchToolSelect &&
			supportsFileSearch &&
			!(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort)
		) {
			tools.push({ type: 'file_search' });
		} else {
			fileSearchCodeInterpreterUnusedFiles.push(...allFSPrivateFiles.map((f) => f.id));
		}
		if (
			includeTooling &&
			codeInterpreterToolSelect &&
			supportsCodeInterpreter &&
			!(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort)
		) {
			tools.push({ type: 'code_interpreter' });
		} else {
			fileSearchCodeInterpreterUnusedFiles.push(...allCIPrivateFiles.map((f) => f.id));
		}
		if (
			includeTooling &&
			webSearchToolSelect &&
			supportsWebSearch &&
			!(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort) &&
			((data.isCreating && !createClassicAssistant) || assistantVersion === 3)
		) {
			tools.push({ type: 'web_search' });
		}
		let mcpServersForRequest: MCPServerToolInput[] = [];
		if (
			includeTooling &&
			mcpServerToolSelect &&
			supportsMCPServer &&
			!(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort) &&
			((data.isCreating && !createClassicAssistant) || assistantVersion === 3)
		) {
			tools.push({ type: 'mcp_server' });
			mcpServersForRequest = mcpServersLocal.map(cleanMcpServerForRequest);
		}
		const params = {
			name: preventEdits ? assistant?.name || '' : body.name.toString(),
			interaction_mode: interactionMode,
			description: preventEdits
				? assistant?.description || ''
				: normalizeNewlines(body.description.toString()),
			instructions: preventEdits
				? assistant?.instructions || ''
				: isLectureMode
					? lectureModeInstructions || LECTURE_VIDEO_DEFAULT_INSTRUCTIONS
					: normalizeNewlines(body.instructions?.toString() || ''),
			notes: preventEdits ? assistant?.notes || '' : normalizeNewlines(notes),
			model: isLectureMode
				? data.isCreating
					? latestModelOptions[0]?.value || selectedModel
					: assistant?.model || selectedModel
				: selectedModel,
			tools: includeTooling ? tools : [],
			code_interpreter_file_ids:
				includeTooling &&
				supportsCodeInterpreter &&
				!(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort) &&
				codeInterpreterToolSelect
					? $selectedCodeInterpreterFiles
					: [],
			file_search_file_ids:
				includeTooling &&
				supportsFileSearch &&
				!(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort) &&
				fileSearchToolSelect
					? $selectedFileSearchFiles
					: [],
			temperature: isLectureMode
				? (assistant?.temperature ?? null)
				: supportsTemperature
					? temperatureValue
					: null,
			reasoning_effort: isLectureMode
				? (assistant?.reasoning_effort ?? null)
				: supportsReasoning
					? reasoningEffortValue
					: null,
			verbosity: isLectureMode
				? (assistant?.verbosity ?? null)
				: supportsVerbosity
					? verbosityValue
					: null,
			lecture_video_key:
				isLectureMode &&
				(data.isCreating ||
					(lectureVideoKeyValue.length > 0 && lectureVideoKeyValue !== currentLectureVideoKey))
					? lectureVideoKeyValue
					: undefined,
			published: body.published?.toString() === 'on',
			use_latex: isLectureMode
				? (assistant?.use_latex ?? false)
				: body.use_latex?.toString() === 'on',
			use_image_descriptions: isLectureMode
				? (assistant?.use_image_descriptions ?? false)
				: body.use_image_descriptions?.toString() === 'on',
			hide_prompt: isLectureMode
				? (assistant?.hide_prompt ?? false)
				: body.hide_prompt?.toString() === 'on',
			assistant_should_message_first: assistantShouldMessageFirst,
			create_classic_assistant: createClassicAssistant,
			deleted_private_files: [...$trashPrivateFileIds, ...fileSearchCodeInterpreterUnusedFiles],
			should_record_user_information: shouldRecordNameOrVoice,
			allow_user_file_uploads: allowUserFileUploads,
			allow_user_image_uploads: allowUserImageUploads,
			hide_reasoning_summaries: hideReasoningSummaries,
			hide_file_search_result_quotes: hideFileSearchDocumentNames
				? true
				: hideFileSearchResultQuotes,
			hide_file_search_document_names: hideFileSearchDocumentNames,
			hide_file_search_queries: hideFileSearchQueries,
			hide_web_search_sources: hideWebSearchActions ? true : hideWebSearchSources,
			hide_web_search_actions: hideWebSearchActions,
			mcp_servers: mcpServersForRequest,
			hide_mcp_server_call_details: hideMCPServerCallDetails,
			convert_to_next_gen:
				!data.isCreating && convertToNextGen !== null ? convertToNextGen : undefined
		};
		return params;
	};

	const deletePrivateFiles = async (fileIds: number[]) => {
		const deletePromises = fileIds.map((fileId) =>
			api.deleteUserFile(fetch, data.class.id, data.me.user!.id, fileId)
		);
		const results = await Promise.all(deletePromises);

		let errorMessage = '';
		results.forEach((result) => {
			if (result.$status >= 300) {
				errorMessage += `Warning: Couldn't delete a private file: ${result.detail}\n`;
			}
		});
		if (errorMessage) {
			sadToast(errorMessage);
		}
	};

	let showAssistantInstructionsPreview = false;
	let instructionsPreview = '';
	/**
	 * Preview the assistant instructions.
	 */
	const previewInstructions = async () => {
		instructionsPreview = '';

		const result = await api.previewAssistantInstructions(fetch, data.class.id, {
			instructions
		});
		const expanded = api.expandResponse(result);

		if (expanded.error) {
			sadToast(
				`Could not generate the assistant instructions:\n${expanded.error.detail || 'Unknown error'}`
			);
			return;
		} else {
			instructionsPreview = expanded.data.instructions_preview;
			showAssistantInstructionsPreview = true;
			return;
		}
	};

	/**
	 * Delete the assistant.
	 */
	const deleteAssistant = async (evt: CustomEvent) => {
		evt.preventDefault();
		const private_files = [...allFSPrivateFiles, ...allCIPrivateFiles].map((f) => f.id);

		// Show loading message if there are more than 10 files attached
		if ($selectedFileSearchFiles.length + private_files.length >= 10 || private_files.length >= 5) {
			$loadingMessage = 'Deleting assistant. This may take a while.';
		}
		$loading = true;

		if (!data.assistantId) {
			await deletePrivateFiles($trashPrivateFileIds);
			$loadingMessage = '';
			$loading = false;
			sadToast(`Error: Assistant ID not found.`);
			return;
		}

		const result = await api.deleteAssistant(fetch, data.class.id, data.assistantId);
		if (result.$status >= 300) {
			await deletePrivateFiles($trashPrivateFileIds);
			$loadingMessage = '';
			$loading = false;
			sadToast(`Error deleting assistant: ${JSON.stringify(result.detail, null, '  ')}`);
			return;
		}

		await deletePrivateFiles(private_files);
		$loadingMessage = '';
		$loading = false;
		checkForChanges = false;
		happyToast('Assistant deleted');
		await invalidate(`/group/${$page.params.classId}`);
		await goto(resolve(`/group/${data.class.id}/assistant`));
		return;
	};

	/**
	 * Create/save an assistant when form is submitted.
	 */
	const submitForm = async (evt: SubmitEvent) => {
		evt.preventDefault();
		$loadingMessage = 'Saving assistant...';
		$loading = true;

		const form = evt.target as HTMLFormElement;
		const params = parseFormData(form);

		if (preventEdits && data.assistantId) {
			const result = await api.updateAssistant(fetch, data.class.id, data.assistantId, {
				published: params.published,
				use_image_descriptions: params.use_image_descriptions
			});
			const expanded = api.expandResponse(result);

			if (expanded.error) {
				$loading = false;
				$loadingMessage = '';
				sadToast(`Could not update the assistant:\n${expanded.error.detail || 'Unknown error'}`);
				return;
			} else {
				$loading = false;
				$loadingMessage = '';
				happyToast('Assistant saved.');
				checkForChanges = false;
				await goto(resolve(`/group/${data.class.id}/assistant`), { invalidateAll: true });
				return;
			}
		}

		if (
			data.isCreating &&
			params.interaction_mode === 'lecture_video' &&
			!params.lecture_video_key
		) {
			sadToast('Please provide a lecture video key for Lecture video mode assistants.');
			$loading = false;
			$loadingMessage = '';
			return;
		}

		if (params.file_search_file_ids.length > fileSearchMetadata.max_count) {
			sadToast(`You can only select up to ${fileSearchMetadata.max_count} files for File Search.`);
			$loading = false;
			$loadingMessage = '';
			return;
		}

		if (params.code_interpreter_file_ids.length > codeInterpreterMetadata.max_count) {
			sadToast(
				`You can only select up to ${codeInterpreterMetadata.max_count} files for Code Interpreter.`
			);
			$loading = false;
			$loadingMessage = '';
			return;
		}

		const result = !data.assistantId
			? await api.createAssistant(fetch, data.class.id, params)
			: await api.updateAssistant(fetch, data.class.id, data.assistantId, params);
		const expanded = api.expandResponse(result);

		if (expanded.error) {
			$loading = false;
			$loadingMessage = '';
			sadToast(`Could not save your response:\n${expanded.error.detail || 'Unknown error'}`);
		} else {
			$loading = false;
			$loadingMessage = '';
			happyToast('Assistant saved');
			checkForChanges = false;
			await invalidate(`/group/${$page.params.classId}`);
			await goto(resolve(`/group/${data.class.id}/assistant`));
		}
	};

	const switchAssistantVersion = () => {
		if (!canSwitchAssistantVersion || preventEdits || assistantVersion === null) {
			return;
		}
		const switchingToNextGen = assistantVersion !== 3;
		if (
			!confirm(
				switchingToNextGen
					? 'Convert this assistant to Next-Gen when you save?\n\nDo not use for important assistants where transcription accuracy is critical.'
					: 'Switch this assistant back to Classic when you save?'
			)
		) {
			return;
		}
		alert(
			switchingToNextGen
				? 'After saving, this assistant will be converted to Next-Gen. You can always switch back to Classic later if needed.'
				: 'After saving, this assistant will be switched back to Classic.'
		);
		convertToNextGen = switchingToNextGen;
		forcedAssistantVersion = switchingToNextGen ? 3 : 2;
	};

	// Handle file upload
	const handleUpload = (f: File, onProgress: (p: number) => void) => {
		return api.uploadUserFile(data.class.id, data.me.user!.id, f, { onProgress });
	};

	beforeNavigate(async (nav) => {
		if (!assistantForm || !nav.to) {
			return;
		}

		// Confirm before leaving the page, unless we've decided otherwise (e.g. after saving).
		if (checkForChanges) {
			const params = parseFormData(assistantForm);
			const dirtyFields = findAllDirtyFields(params);
			if (dirtyFields.length > 0) {
				if (
					!confirm(
						`Your changes to the following fields have not been saved:\n\n  ${dirtyFields.join(
							', '
						)}\n\nAre you sure you want to leave this page?`
					)
				) {
					nav.cancel();
					return;
				}
			}

			// Delete any private files that were uploaded but not saved.
			const filesToDelete = [...$privateUploadFSFileInfo, ...$privateUploadCIFileInfo]
				.filter((f) => f.state === 'success')
				.map((f) => f.response as ServerFile);

			if (filesToDelete.length) {
				$loadingMessage = 'Cleaning up files you uploaded...';
				$loading = true;
				await deletePrivateFiles(filesToDelete.map((f) => f.id));
				$loading = false;
				$loadingMessage = '';
			}

			// Now manually navigate to the intended destination
			checkForChanges = false;
			return;
		}
	});
</script>

<div class="h-full w-full overflow-y-auto p-12">
	<div class="flex flex-row justify-between">
		<Heading tag="h2" class="mb-6 font-serif text-3xl font-medium text-blue-dark-40">
			{#if data.isCreating}
				New assistant
			{:else if preventEdits}
				View assistant
			{:else}
				Edit assistant
			{/if}
		</Heading>
		{#if !data.isCreating && !preventEdits}
			<div class="flex shrink-0 items-start">
				<Button
					pill
					size="sm"
					class="border border-red-700 bg-white text-red-700 hover:bg-red-700 hover:text-white"
					type="button"
					onclick={() => (deleteModal = true)}
					disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}>Delete assistant</Button
				>

				<Modal bind:open={deleteModal} size="xs" autoclose>
					<ConfirmationModal
						warningTitle={`Delete ${data?.assistant?.name || 'this assistant'}?`}
						warningDescription="All threads associated with this assistant will become read-only."
						warningMessage="This action cannot be undone."
						cancelButtonText="Cancel"
						confirmText="delete"
						confirmButtonText="Delete assistant"
						on:cancel={() => (deleteModal = false)}
						on:confirm={deleteAssistant}
					/>
				</Modal>
			</div>
		{/if}
	</div>
	{#if assistantStatusUpdates.length > 0}
		<fieldset class="-mt-2 mb-6 min-w-0 rounded-2xl border border-gray-200 bg-white px-4 py-3">
			<legend
				class="ml-2.5 px-2 text-[11px] font-semibold tracking-[0.18em] text-gray-600 uppercase"
			>
				Issues affecting this assistant
			</legend>
			<div class="-mx-3"><StatusErrors {assistantStatusUpdates} /></div>
		</fieldset>
	{/if}
	{#if preventEdits}
		<div
			class="border-gradient-to-r col-span-2 mb-4 flex items-center rounded-lg bg-gradient-to-r from-gray-800 to-gray-600 p-4 text-white"
		>
			<LockSolid class="mr-3 h-8 w-8" />
			<span>
				This assistant is locked and cannot be edited. To make changes, create a new assistant. You
				can still publish or unpublish this assistant if you have the necessary permissions. For
				more information, contact your Group's administrator.
			</span>
		</div>
	{/if}
	<Modal
		title="Assistant Prompt Preview"
		size="lg"
		bind:open={showAssistantInstructionsPreview}
		autoclose
		outsideclose
		><span class="whitespace-pre-wrap text-gray-700"><Sanitize html={instructionsPreview} /></span
		></Modal
	>
	{#if showMCPServerModal}
		<MCPServerModal
			mcpServerRecordFromServer={mcpServerEditFromServer}
			mcpServerLocalDraft={mcpServerEdit}
			{mcpServerEditIndex}
			on:save={(e) => saveMCPServerAndCloseModal(e.detail.mcpServer, e.detail.index)}
			on:close={() => resetDraftMCPServerAndCloseModal()}
		/>
	{/if}

	<form onsubmit={submitForm} bind:this={assistantForm}>
		<div class="mb-4">
			<Label class="pb-1" for="name">Name</Label>
			<Input id="name" name="name" bind:value={assistantName} disabled={preventEdits} />
		</div>
		<div class="mb-4">
			<Label for="interactionMode">Interaction Mode</Label>
			<Helper class="pb-1"
				>Choose how users will primarily interact with this assistant.{#if showLectureModeOption && !data.isCreating}
					&nbsp;Lecture video mode cannot be changed after assistant creation.{/if}</Helper
			>
			<ButtonGroup>
				{#if !isEditingLectureAssistant && chatModelCount !== 0}
					<RadioButton
						value="chat"
						bind:group={interactionMode}
						disabled={preventEdits}
						onchange={changeInteractionMode}
						class={`${preventEdits ? 'hover:bg-transparent' : ''} select-none`}
						><div class="flex flex-row items-center gap-2">
							{#if interactionMode === 'chat'}<MessageDotsSolid
									class="h-6 w-6"
								/>{:else}<MessageDotsOutline class="h-6 w-6" />{/if}Chat mode
						</div></RadioButton
					>
				{/if}
				{#if !isEditingLectureAssistant && audioModelCount !== 0}
					<RadioButton
						value="voice"
						bind:group={interactionMode}
						disabled={preventEdits}
						onchange={changeInteractionMode}
						class={`${preventEdits ? 'hover:bg-transparent' : ''} select-none`}
						><div class="flex flex-row items-center gap-2">
							{#if interactionMode === 'voice'}<MicrophoneSolid
									class="h-5 w-5"
								/>{:else}<MicrophoneOutline class="h-5 w-5" />{/if}Voice mode
						</div></RadioButton
					>
				{/if}
				{#if showLectureModeOption && chatModelCount !== 0}
					<RadioButton
						value="lecture_video"
						bind:group={interactionMode}
						disabled={preventEdits || !data.isCreating}
						onchange={changeInteractionMode}
						class={`${preventEdits || !data.isCreating ? 'hover:bg-transparent' : ''} select-none`}
						><div id="lecture-video-admin-tooltip" class="flex flex-row items-center gap-2">
							{#if interactionMode === 'lecture_video'}<ClapperboardPlaySolid
									class="h-5 w-5"
								/>{:else}<PersonChalkboardOutline class="h-5 w-5" />{/if}Lecture Video mode
							<DropdownBadge
								extraClasses="border-red-400 from-red-100 to-red-200 text-red-800 py-0 px-1"
								><span slot="name">In Development</span></DropdownBadge
							>
						</div></RadioButton
					>
					<Tooltip
						triggeredBy="#lecture-video-admin-tooltip"
						class="z-100 text-sm font-light"
						hidden={!data.isCreating}
						arrow={false}>Only admins can see and select this option</Tooltip
					>
				{/if}
			</ButtonGroup>
		</div>
		{#if !isLectureMode}
			<div class="mb-4">
				<Label for="model">Model</Label>
				<Helper class="pb-1"
					>Select the model to use for this assistant. You can update your model selection at any
					time. Latest Models will always point to the latest version of the model available. Select
					a Pinned Model Version to continue using a specific model version regardless of future
					model updates. See <a
						href="https://platform.openai.com/docs/models"
						rel="noopener noreferrer"
						target="_blank"
						class="underline">OpenAI's Documentation</a
					> for detailed descriptions of model capabilities.</Helper
				>
				{#if selectedModelDeprecated}
					<div
						class="mb-2 flex flex-row items-center gap-4 rounded-lg border border-amber-400 bg-gradient-to-b from-amber-50 to-amber-100 p-4 py-2 text-amber-800"
					>
						<ArchiveOutline class="h-8 w-8 text-amber-800" strokeWidth="1.5" />
						<div class="flex flex-col">
							<span class="text-sm font-semibold">Legacy Model</span>
							<span class="text-xs"
								>This model is no longer available for new assistants on PingPong. You can continue
								using it with this assistant, but you won't be able to switch back after selecting a
								new model. <span class="font-semibold"
									>We recommend upgrading to one of the latest models for the best experience.</span
								></span
							>
						</div>
					</div>
				{/if}
				{#if supportsVision && visionSupportOverride === false}
					<div
						class="mb-2 flex flex-row items-center gap-4 rounded-lg border border-amber-400 bg-gradient-to-b from-amber-50 to-amber-100 p-4 py-2 text-amber-800"
					>
						<div class="relative flex h-8 w-12 items-center justify-center">
							<BanOutline class="absolute z-10 h-12 w-12 text-amber-600" strokeWidth="1.5" />
							<FileImageOutline class="h-8 w-8 text-stone-400" strokeWidth="1" />
						</div>
						<div class="flex flex-col">
							<span class="text-sm font-semibold"
								>Vision capabilities are currently unavailable</span
							>
							<span class="text-xs"
								>Your AI Provider doesn't support Vision capabilities for this model. We are working
								on adding Vision support. You can still use supported image files with Code
								Interpreter.</span
							>
						</div>
					</div>
				{/if}
				<div class="flex flex-row gap-2">
					{#key selectedModel}
						<DropdownContainer
							footer
							placeholder={selectedModelName || 'Select a model...'}
							optionNodes={modelNodes}
							optionHeaders={modelHeaders}
							disabled={preventEdits}
							bind:selectedOption={selectedModel}
							bind:dropdownOpen
						>
							<DropdownHeader
								order={1}
								name="latest-models"
								colorClasses="from-orange-dark to-orange"
								topHeader>Latest Models</DropdownHeader
							>
							<ModelDropdownOptions
								modelOptions={latestModelOptions}
								{selectedModel}
								{updateSelectedModel}
								{allowVisionUpload}
								headerClass="latest-models"
								bind:modelNodes
								bind:modelHeaders
							/>
							<DropdownHeader
								order={2}
								name="versioned-models"
								colorClasses="from-blue-dark-40 to-blue-dark-30">Pinned Models</DropdownHeader
							>
							<ModelDropdownOptions
								modelOptions={versionedModelOptions}
								{selectedModel}
								{updateSelectedModel}
								{allowVisionUpload}
								headerClass="versioned-models"
								bind:modelNodes
								bind:modelHeaders
								smallNameText
							/>
							<div slot="footer">
								<DropdownFooter
									colorClasses="from-gray-800 to-gray-600"
									hoverable
									hoverColorClasses="hover:from-gray-900 hover:to-gray-700"
									link="https://platform.openai.com/docs/models"
									><div class="flex flex-row justify-between">
										<div class="flex flex-row gap-2">
											<QuestionCircleSolid /> Unsure which model to choose? Check out OpenAI's documentation
										</div>
										<ArrowUpRightFromSquareOutline />
									</div></DropdownFooter
								>
							</div>
						</DropdownContainer>
					{/key}
					{#if allowVisionUpload}
						<Badge
							class="flex flex-row items-center gap-x-2 rounded-lg border px-2 py-0.5 text-xs normal-case {finalVisionSupport
								? 'border-green-400 bg-gradient-to-b from-emerald-100 to-emerald-200 text-green-800'
								: 'border-gray-100 bg-gray-50 text-gray-600'}"
							>{#if finalVisionSupport}<ImageOutline size="sm" />{:else}<CloseOutline
									size="sm"
								/>{/if}
							<div class="flex flex-col">
								<div>{finalVisionSupport ? 'Vision' : 'No Vision'}</div>
								<div>capabilities</div>
							</div></Badge
						>
					{/if}
				</div>
			</div>
		{/if}

		<div class="col-span-2 mb-4">
			<Label for="description">Description</Label>
			<Helper class="pb-1"
				>Describe what this assistant does. This information is <strong>not</strong> included in the
				prompt, but <strong>is</strong> shown to users.</Helper
			>
			<Textarea
				id="description"
				name="description"
				bind:value={description}
				disabled={preventEdits}
			/>
		</div>
		{#if isLectureMode}
			<div class="col-span-2 mb-4">
				<Label for="lecture_video_key">Lecture Video Key</Label>
				<Helper class="pb-1"
					>{#if data.isCreating}Provide the key for the lecture video this assistant should use.{:else}Edit
						this key to replace the current lecture video.{/if}</Helper
				>
				<div class="relative w-full pt-2 pb-2">
					<ButtonGroup class="w-full">
						<InputAddon>
							<FileVideoOutline class="h-6 w-6" />
						</InputAddon>
						<Input
							id="lecture_video_key"
							name="lecture_video_key"
							autocomplete="off"
							placeholder="video_name.mp4"
							bind:value={lectureVideoKey}
							disabled={preventEdits}
							defaultClass="block w-full disabled:cursor-not-allowed disabled:opacity-50 rtl:text-right font-mono"
						/>
					</ButtonGroup>
				</div>
			</div>
		{/if}
		{#if !isLectureMode}
			<div class="col-span-2 mb-4">
				<div class="flex flex-row items-end justify-between">
					<div>
						<Label for="instructions">Instructions</Label>
						<Helper class="pb-1"
							>This is the prompt the language model will use to generate responses.</Helper
						>
					</div>
					<Button
						class="mb-1 flex max-h-fit max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
						onclick={previewInstructions}
						type="button"
						disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}
					>
						Preview
					</Button>
				</div>
				<Textarea
					id="instructions"
					name="instructions"
					rows={6}
					bind:value={instructions}
					disabled={preventEdits}
				/>
			</div>
			<div class="col-span-2 mb-4">
				<Checkbox id="hide_prompt" name="hide_prompt" disabled={preventEdits} checked={hidePrompt}
					>Hide Prompt</Checkbox
				>
				<Helper
					>Hide the prompt from other users. When checked, only the moderation team and the
					assistant's creator will be able to see this prompt.</Helper
				>
			</div>
			<div class="col-span-2 mb-4">
				{#if interactionMode === 'chat'}
					<Checkbox id="use_latex" name="use_latex" disabled={preventEdits} checked={useLatex}
						>Use LaTeX</Checkbox
					>
					<Helper>Enable LaTeX formatting for assistant responses.</Helper>
				{:else}
					<div class="flex flex-col gap-y-1">
						<Badge
							class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
							><CloseOutline size="sm" />
							<div>No LaTeX formatting for assistant responses</div>
						</Badge>
						<Helper
							>This interaction mode does not support LaTeX formatting for assistant responses. To
							use LaTeX formatting, switch to Chat mode.</Helper
						>
					</div>
				{/if}
			</div>
			<div class="col-span-2 mb-4">
				<Label for="tools">Tools</Label>
				<Helper>Select tools available to the assistant when generating a response.</Helper>
			</div>
			{#if supportsReasoning && reasoningEffortValue === -1 && supportsNoneReasoningEffort}
				<div class="col-span-2 mb-3">
					<div
						class="flex flex-row items-center justify-between gap-x-4 rounded-lg border border-amber-400 bg-gradient-to-b from-amber-50 to-amber-100 p-3 text-amber-800"
					>
						<div class="flex flex-row items-center gap-x-3">
							<LightbulbSolid size="md" class="shrink-0" />
							<div class="flex flex-col text-xs">
								<span class="font-bold">Tool reliability may be reduced</span>
								<span
									>The current <span class="font-mono">none</span> reasoning effort prioritizes speed,
									which can impact the reliability of tool calls. You can adjust this setting in Advanced
									Options.</span
								>
							</div>
						</div>
						<Button
							size="xs"
							color="light"
							class="shrink-0 border-amber-400 bg-white/60 px-3 py-0.5 text-amber-900 hover:bg-white"
							disabled={preventEdits}
							onclick={async () => {
								if (!advancedOptionsOpen) {
									advancedOptionsOpen = true;
									await tick();
									await new Promise((resolve) => setTimeout(resolve, 150));
								}
								const el = document.getElementById('reasoning-effort');
								if (el) {
									el.scrollIntoView({ behavior: 'smooth', block: 'center' });
								}
							}}>Adjust in Advanced Options</Button
						>
					</div>
				</div>
			{/if}
			{#if !supportsFileSearch}
				<div class="col-span-2 mb-3">
					<div class="flex flex-col gap-y-1">
						<Badge
							class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
							><CloseOutline size="sm" />
							<div>No File Search capabilities</div>
						</Badge>
						<Helper
							>This model does not support File Search capabilities. To use File Search, select a
							different model.</Helper
						>
					</div>
				</div>
			{:else if supportsFileSearch && supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort}
				<div class="col-span-2 mb-3">
					<div class="flex flex-col gap-y-1">
						<Badge
							class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
							><CloseOutline size="sm" />
							<div>No File Search capabilities in Minimal reasoning effort</div>
						</Badge>
						<Helper
							>Minimal reasoning effort does not support File Search capabilities. To use File
							Search, select a higher reasoning effort level.</Helper
						>
					</div>
				</div>
			{:else}
				<div class="col-span-2 mb-4">
					<Checkbox
						id={fileSearchMetadata.value}
						name={fileSearchMetadata.value}
						checked={supportsFileSearch && (fileSearchToolSelect || false)}
						disabled={!supportsFileSearch || preventEdits}
						onchange={() => {
							fileSearchToolSelect = !fileSearchToolSelect;
						}}>{fileSearchMetadata.name}</Checkbox
					>
					<Helper>{fileSearchMetadata.description}</Helper>
				</div>
			{/if}
			<div class="col-span-2 mb-4">
				{#if !supportsCodeInterpreter}
					<div class="flex flex-col gap-y-1">
						<Badge
							class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
							><CloseOutline size="sm" />
							<div>No Code Interpreter capabilities</div>
						</Badge>
						<Helper
							>This model does not support Code Interpreter capabilities. To use Code Interpreter,
							select a different model.</Helper
						>
					</div>
				{:else if supportsCodeInterpreter && supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort}
					<div class="col-span-2 mb-3">
						<div class="flex flex-col gap-y-1">
							<Badge
								class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
								><CloseOutline size="sm" />
								<div>No Code Interpreter capabilities in Minimal reasoning effort</div>
							</Badge>
							<Helper
								>Minimal reasoning effort does not support Code Interpreter capabilities. To use
								Code Interpreter, select a higher reasoning effort level.</Helper
							>
						</div>
					</div>
				{:else}
					<Checkbox
						id={codeInterpreterMetadata.value}
						name={codeInterpreterMetadata.value}
						disabled={preventEdits || !supportsCodeInterpreter}
						checked={supportsCodeInterpreter && (codeInterpreterToolSelect || false)}
						onchange={() => {
							codeInterpreterToolSelect = !codeInterpreterToolSelect;
						}}>{codeInterpreterMetadata.name}</Checkbox
					>
					<Helper>{codeInterpreterMetadata.description}</Helper>
				{/if}
			</div>
			{#if !data?.enforceClassicAssistants}
				<div class="col-span-2 mb-4">
					{#if (data.isCreating && createClassicAssistant) || (!data.isCreating && assistantVersion !== 3)}
						<div class="col-span-2 mb-3">
							<div class="flex flex-col gap-y-1">
								<Badge
									class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
									><CloseOutline size="sm" />
									<div>No Web Search capabilities in Classic Assistants</div>
								</Badge>
								<Helper
									>Classic Assistants do not support Web Search capabilities. To use Web Search,
									create a Next-Gen Assistant.</Helper
								>
							</div>
						</div>
					{:else if !supportsWebSearch}
						<div class="flex flex-col gap-y-1">
							<Badge
								class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
								><CloseOutline size="sm" />
								<div>No Web Search capabilities</div>
							</Badge>
							<Helper
								>This model does not support Web Search capabilities. To use Web Search, select a
								different model.</Helper
							>
						</div>
					{:else if supportsWebSearch && supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort}
						<div class="col-span-2 mb-3">
							<div class="flex flex-col gap-y-1">
								<Badge
									class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
									><CloseOutline size="sm" />
									<div>No Web Search capabilities in Minimal reasoning effort</div>
								</Badge>
								<Helper
									>Minimal reasoning effort does not support Web Search capabilities. To use Web
									Search, select a higher reasoning effort level.</Helper
								>
							</div>
						</div>
					{:else}
						<Checkbox
							id={webSearchMetadata.value}
							name={webSearchMetadata.value}
							disabled={preventEdits || !supportsWebSearch}
							checked={supportsWebSearch && (webSearchToolSelect || false)}
							onchange={() => {
								webSearchToolSelect = !webSearchToolSelect;
							}}
							><div class="flex flex-wrap gap-1.5">
								<div>{webSearchMetadata.name}</div>
							</div></Checkbox
						>
						<Helper>{webSearchMetadata.description}</Helper>
					{/if}
				</div>
			{/if}
			{#if !data?.enforceClassicAssistants}
				<div class="col-span-2 mb-4">
					{#if (data.isCreating && createClassicAssistant) || (!data.isCreating && assistantVersion !== 3)}
						<div class="col-span-2 mb-3">
							<div class="flex flex-col gap-y-1">
								<Badge
									class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
									><CloseOutline size="sm" />
									<div>No MCP Server capabilities in Classic Assistants</div>
								</Badge>
								<Helper
									>Classic Assistants do not support MCP Server capabilities. To use MCP Server,
									create a Next-Gen Assistant.</Helper
								>
							</div>
						</div>
					{:else if !supportsMCPServer}
						<div class="flex flex-col gap-y-1">
							<Badge
								class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
								><CloseOutline size="sm" />
								<div>No MCP Server capabilities</div>
							</Badge>
							<Helper
								>This model does not support MCP Server capabilities. To use MCP Server, select a
								different model.</Helper
							>
						</div>
					{:else if supportsMCPServer && supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort}
						<div class="col-span-2 mb-3">
							<div class="flex flex-col gap-y-1">
								<Badge
									class="flex max-w-fit shrink-0 flex-row items-center gap-x-2 rounded-lg border border-gray-400 bg-gradient-to-b from-gray-100 to-gray-200 px-2 py-0.5 text-xs text-gray-800 normal-case"
									><CloseOutline size="sm" />
									<div>No MCP Server capabilities in Minimal reasoning effort</div>
								</Badge>
								<Helper
									>Minimal reasoning effort does not support MCP Server capabilities. To use MCP
									Server, select a higher reasoning effort level.</Helper
								>
							</div>
						</div>
					{:else}
						<Checkbox
							id={mcpServerMetadata.value}
							name={mcpServerMetadata.value}
							disabled={preventEdits || !supportsMCPServer}
							checked={supportsMCPServer && (mcpServerToolSelect || false)}
							onchange={() => {
								mcpServerToolSelect = !mcpServerToolSelect;
							}}
							><div class="flex flex-wrap gap-1.5">
								<div>{mcpServerMetadata.name}</div>
								<DropdownBadge
									extraClasses="border-amber-400 from-amber-100 to-amber-200 text-amber-800 py-0 px-1"
									><span slot="name">Preview</span></DropdownBadge
								>
							</div></Checkbox
						>
						<Helper>{mcpServerMetadata.description}</Helper>
					{/if}
				</div>
			{/if}

			{#if fileSearchToolSelect && supportsFileSearch && !(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort)}
				<div class="col-span-2 mb-4">
					<Label for="selectedFileSearchFiles">{fileSearchMetadata.name} Files</Label>
					<Helper class="pb-1"
						>Select which files this assistant should use for {fileSearchMetadata.name}. You can
						select up to {fileSearchMetadata.max_count} files. You can also upload private files specific
						to this assistant. If you want to make files available for the entire group, upload them in
						the Manage Group page.</Helper
					>
					<MultiSelectWithUpload
						name="selectedFileSearchFiles"
						items={fileSearchOptions}
						bind:value={selectedFileSearchFiles}
						disabled={$loading ||
							!handleUpload ||
							uploadingFSPrivate ||
							preventEdits ||
							!supportsFileSearch}
						privateFiles={allFSPrivateFiles}
						uploading={uploadingFSPrivate}
						upload={handleUpload}
						accept={data.uploadInfo.fileTypes({
							file_search: true,
							code_interpreter: false,
							vision: false
						})}
						maxSize={data.uploadInfo.class_file_max_size}
						maxCount={fileSearchMetadata.max_count}
						uploadType="File Search"
						on:error={(e) => sadToast(e.detail.message)}
						on:change={handleFSPrivateFilesChange}
						on:delete={removePrivateFiles}
					/>
				</div>
			{/if}

			{#if codeInterpreterToolSelect && supportsCodeInterpreter && !(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort)}
				<div class="col-span-2 mb-4">
					<Label for="selectedCodeInterpreterFiles">{codeInterpreterMetadata.name} Files</Label>
					<Helper class="pb-1"
						>Select which files this assistant should use for {codeInterpreterMetadata.name}. You
						can select up to {codeInterpreterMetadata.max_count} files. You can also upload private files
						specific to this assistant. If you want to make files available for the entire group, upload
						them in the Manage Group page.</Helper
					>
					<MultiSelectWithUpload
						name="selectedCodeInterpreterFiles"
						items={codeInterpreterOptions}
						bind:value={selectedCodeInterpreterFiles}
						disabled={$loading ||
							!handleUpload ||
							uploadingCIPrivate ||
							preventEdits ||
							!supportsCodeInterpreter}
						privateFiles={allCIPrivateFiles}
						uploading={uploadingCIPrivate}
						upload={handleUpload}
						accept={data.uploadInfo.fileTypes({
							file_search: false,
							code_interpreter: true,
							vision: false
						})}
						maxSize={data.uploadInfo.class_file_max_size}
						maxCount={codeInterpreterMetadata.max_count}
						uploadType="Code Interpreter"
						on:error={(e) => sadToast(e.detail.message)}
						on:change={handleCIPrivateFilesChange}
						on:delete={removePrivateFiles}
					/>
				</div>
			{/if}

			{#if mcpServerToolSelect && supportsMCPServer && !(supportsReasoning && reasoningEffortValue === -1 && !supportsNoneReasoningEffort)}
				<div class="col-span-2 mb-4">
					<Label for="mcpServers">MCP Server Configuration</Label>
					<Helper class="pb-1"
						>Configure which remote MCP servers this assistant can use. In addition to built-in
						tools you make available to the assistant, you can give assistants new capabilities
						using remote MCP servers. These tools give the assistant the ability to connect to and
						control external services when needed to respond to a user's prompt.
					</Helper>
					<div class="mt-4 rounded-2xl border border-gray-200 bg-white">
						<div
							class="flex flex-col gap-3 border-b border-gray-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
						>
							<div class="text-sm font-semibold text-gray-900">Configured servers</div>
							<Button
								type="button"
								size="xs"
								color="light"
								class="w-fit"
								onclick={() => (showMCPServerModal = true)}
								disabled={preventEdits}>Add MCP Server</Button
							>
						</div>
						<div
							class="hidden border-b border-gray-100 px-4 py-2 text-xs tracking-[0.14em] text-gray-500 uppercase sm:grid sm:grid-cols-12 sm:gap-3"
						>
							<div class="sm:col-span-4">Server Name</div>
							<div class="sm:col-span-4">URL</div>
							<div class="sm:col-span-2">Authentication</div>
							<div class="text-center sm:col-span-1">Enabled</div>
							<div class="text-right sm:col-span-1">Actions</div>
						</div>
						{#if mcpServersLocal.length === 0}
							<div class="px-4 py-6 text-sm text-gray-500">No MCP servers configured yet.</div>
						{:else}
							{#each mcpServersLocal as server, index (index)}
								<div class="border-t border-gray-100 px-4 py-3">
									<div class="flex flex-col gap-3 sm:grid sm:grid-cols-12 sm:items-center sm:gap-3">
										<div class="sm:col-span-4">
											<div class="truncate text-sm text-gray-700" title={server.display_name}>
												{server.display_name}
											</div>
										</div>
										<div class="sm:col-span-4">
											<div class="truncate text-sm text-gray-700" title={server.server_url}>
												{server.server_url}
											</div>
										</div>
										<div class="sm:col-span-2">
											<div class="text-sm text-gray-600">{mcpAuthTypeLabels[server.auth_type]}</div>
										</div>
										<div class="sm:col-span-1 sm:text-center">
											<input
												type="checkbox"
												class="h-4 w-4 rounded border-gray-300 text-blue-dark-40 focus:ring-blue-dark-40 disabled:opacity-50"
												bind:checked={server.enabled}
												disabled={preventEdits}
												aria-label="Enable MCP server"
											/>
										</div>
										<div class="flex flex-wrap items-center gap-2 sm:col-span-1 sm:justify-end">
											<Button
												type="button"
												size="xs"
												color="light"
												class="w-fit"
												onclick={() => {
													mcpServerEditIndex = index;
													showMCPServerModal = true;
												}}
												disabled={preventEdits}>Edit</Button
											>
											<Button
												type="button"
												size="xs"
												color="light"
												class="w-fit text-red-600"
												onclick={() => removeServer(index)}
												disabled={preventEdits}>Remove</Button
											>
										</div>
									</div>
								</div>
							{/each}
						{/if}
					</div>
				</div>
			{/if}
		{/if}

		<div class="col-span-2 mb-4">
			<Checkbox
				id="published"
				disabled={!canPublish && !isPublished}
				name="published"
				checked={isPublished}>Publish</Checkbox
			>
			{#if !canPublish}
				<Helper
					>You do not have permissions to change the published status of this assistant. Contact
					your administrator if you need to share this assistant.</Helper
				>
			{:else}
				<Helper
					>By default only you can see and interact with this assistant. If you would like to share
					the assistant with the rest of your group, select this option.</Helper
				>
			{/if}
		</div>

		{#if visionSupportOverride === false && !isLectureMode}
			<div class="col-span-2 mb-4">
				<Checkbox
					id="use_image_descriptions"
					name="use_image_descriptions"
					class="mb-1"
					checked={useImageDescriptions}
					><div class="flex flex-row gap-1.5">
						<div>Enable Vision capabilities through Image Descriptions</div>
						<DropdownBadge
							extraClasses="border-amber-400 from-amber-100 to-amber-200 text-amber-800 py-0 px-1"
							><span slot="name">Experimental</span></DropdownBadge
						>
					</div></Checkbox
				>
				<Helper
					>Your AI Provider doesn't support direct image analysis for this model. Enable this option
					to try a new experimental feature that uses image descriptions to provide Vision
					capabilities. This feature is still under active development and might produce unexpected
					or inaccurate results. To share your thoughts or report any issues, <a
						href="https://airtable.com/appR9m6YfvPTg1H3d/pagS1VLdLrPSbeqoN/form"
						class="underline"
						rel="noopener noreferrer"
						target="_blank">use this form</a
					>.
				</Helper>
			</div>
		{/if}

		<div class="my-5 w-full">
			<Accordion>
				<AccordionItem
					bind:open={advancedOptionsOpen}
					paddingDefault="px-5 py-3"
					defaultClass="px-6 py-4 flex items-center justify-between w-full font-medium text-left rounded-sm border-gray-200 dark:border-gray-700"
					activeClass="rounded-b-none"
					borderOpenClass="rounded-b-lg border-s border-e"
				>
					<span slot="header"
						><div class="flex flex-row items-center space-x-2 py-0">
							<div><CogOutline size="md" strokeWidth="2" /></div>
							<div class="text-sm">Advanced Options</div>
						</div></span
					>
					<div class="flex flex-col gap-4 px-1">
						{#if !isLectureMode}
							<div class="col-span-2 mb-1">
								<Checkbox
									id="assistant_should_message_first"
									name="assistant_should_message_first"
									disabled={preventEdits}
									bind:checked={assistantShouldMessageFirst}
									>Assistant Should Message First</Checkbox
								>
								<Helper
									>Control whether the assistant should initiate the conversation. When checked,
									users will be able to send their first message after the assistant responds.</Helper
								>
							</div>

							<hr />
						{/if}

						<div class="col-span-2 mb-1">
							<Checkbox
								id="should_record_user_information"
								name="should_record_user_information"
								disabled={preventEdits || isClassPrivate}
								bind:checked={shouldRecordNameOrVoice}
								><div class="flex flex-row gap-1">
									<div>
										{#if interactionMode === 'voice'}Record User Name and Conversation{/if}
										{#if interactionMode !== 'voice'}Record User Name{/if}
									</div>
									{#if isClassPrivate}<div>&middot;</div>
										<div>Unavailable for Private Groups</div>{/if}
								</div></Checkbox
							>
							<Helper
								>{#if interactionMode !== 'voice'}Control whether moderators should be able to view
									the user's name when viewing a thread. When checked, users will be given a notice
									that their name will be visible to moderators. Published threads will display
									pseudonyms to members. Only threads <span class="font-extrabold"
										>created while this option is enabled</span
									> will show the user's name.{:else}Control whether moderators should be able to
									view the user's name and listen to a recording of their conversation when viewing
									a thread. When checked, users will be given a notice that their name will be
									visible to moderators and that their conversation will be recorded. Published
									threads will still display pseudonyms to members. Members cannot listen to
									recordings of published threads. Only threads <span class="font-extrabold"
										>created while this option is enabled</span
									> will show the user's name and be recorded.
								{/if}</Helper
							>
						</div>
						{#if !isLectureMode}
							<hr />
						{/if}

						{#if !isLectureMode}
							<div class="col-span-2 mb-1">
								<Checkbox
									id="allow_user_file_uploads"
									name="allow_user_file_uploads"
									disabled={preventEdits}
									bind:checked={allowUserFileUploads}
									><div class="flex flex-row gap-1">
										<div>Allow Users to Upload Files</div>
									</div></Checkbox
								>
								<Helper
									>Control whether users can upload their own files when interacting with this
									assistant. When unchecked, users will not be able to attach their own files to
									messages, even if the assistant has file search or code interpreter enabled. Files
									that you add to the assistant will still be available for the assistant to use. <b
										>This setting will only apply when you enable File Search or Code Interpreter in
										Chat Mode models.</b
									></Helper
								>
							</div>

							<div class="col-span-2 mb-1">
								<Checkbox
									id="allow_user_image_uploads"
									name="allow_user_image_uploads"
									disabled={preventEdits}
									bind:checked={allowUserImageUploads}
									><div class="flex flex-row gap-1">
										<div>Allow Users to Upload Images</div>
									</div></Checkbox
								>
								<Helper
									>Control whether users can upload their own images when interacting with this
									assistant. When unchecked, users will not be able to attach their own images to
									messages, even if the assistant's model has Vision capabilities. <b
										>This setting will only apply to Chat Mode models with Vision capabilities{visionSupportOverride ===
										false
											? ', or when you enable Vision capabilities through Image Descriptions.'
											: '.'}</b
									></Helper
								>
							</div>
							<hr />
							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_file_search_queries"
									name="hide_file_search_queries"
									disabled={preventEdits}
									bind:checked={hideFileSearchQueries}
									><div class="flex flex-row gap-1">
										<div>Hide File Search Queries from Members</div>
									</div></Checkbox
								>
								<Helper
									>Control whether members can see the queries the assistant uses for file searches.
									Depending on your prompt, these queries may contain sensitive information or
									provide information about how you have designed the assistant. When checked,
									members will not see the queries. Moderators can always review file search
									queries. <b
										>This setting will only apply to Chat Mode models with File Search enabled.</b
									></Helper
								>
							</div>

							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_file_search_result_quotes"
									name="hide_file_search_result_quotes"
									class={hideFileSearchDocumentNames
										? 'text-gray-400 contrast-50 grayscale'
										: 'text-gray-800 contrast-100 grayscale-0'}
									disabled={preventEdits || hideFileSearchDocumentNames}
									bind:checked={hideFileSearchResultQuotes}
									><div class="flex flex-row gap-1">
										<div>Hide File Search Result Quotes from Members</div>
										{#if hideFileSearchDocumentNames}<div>&middot;</div>
											<div>"Completely Hide File Search Results" selected</div>{/if}
									</div></Checkbox
								>
								<Helper
									>Control whether members can see the text the assistant retrieves from each file
									during File Search. Depending on the materials you make available to the
									assistant, quotes may contain sensitive information like answer keys. When
									checked, members will not see the document quotes returned during file searches.
									Moderators can always review file search results. <b
										>This setting will only apply to Chat Mode models with File Search enabled.</b
									></Helper
								>
							</div>
							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_file_search_document_names"
									name="hide_file_search_document_names"
									disabled={preventEdits}
									bind:checked={hideFileSearchDocumentNames}
									><div class="flex flex-row gap-1">
										<div>Completely Hide File Search Results from Members</div>
									</div></Checkbox
								>
								<Helper
									>Hide the names of the documents the assistant retrieves in file searches from
									members, on top of quotes. In some cases, document names may contain sensitive
									information. When checked, PingPong will completely hide file search results.
									Moderators can always review file search results. <b
										>This setting will only apply to Chat Mode models with File Search enabled.</b
									></Helper
								>
							</div>

							<hr />
							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_web_search_sources"
									name="hide_web_search_sources"
									disabled={preventEdits || hideWebSearchActions}
									class={hideWebSearchActions
										? 'text-gray-400 contrast-50 grayscale'
										: 'text-gray-800 contrast-100 grayscale-0'}
									bind:checked={hideWebSearchSources}
									><div class="flex flex-row gap-1">
										<div>Hide Web Search Sources from Members</div>
										{#if hideWebSearchActions}<div>&middot;</div>
											<div>"Completely Hide Web Search Actions" selected</div>{/if}
									</div></Checkbox
								>
								<Helper
									>When the assistant uses web search, it may consider a number of sources before
									drafting its response. Many of the sources are often not used in the final
									response. Control whether members can see all sources. When checked, members will
									not see the sources the assistant used during web searches. Moderators can always
									review web search sources. <b
										>This setting will only apply to Chat Mode models with Web Search enabled.</b
									></Helper
								>
							</div>

							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_web_search_actions"
									name="hide_web_search_actions"
									disabled={preventEdits}
									bind:checked={hideWebSearchActions}
									><div class="flex flex-row gap-1">
										<div>Completely Hide Web Search Actions from Members</div>
									</div></Checkbox
								>
								<Helper
									>When the assistant uses web search, it may perform various actions such as
									querying search engines, clicking on links, and extracting information. This
									setting controls whether members can see these web search actions. When checked,
									members will see that the assistant is searching the web without revealing
									specific actions. Moderators can always review web search actions. <b
										>This setting will only apply to Chat Mode models with Web Search enabled.</b
									></Helper
								>
							</div>
							<div class="col-span-2 mb-1">
								<div
									class="flex flex-row items-center justify-between gap-x-4 rounded-lg border border-blue-400 bg-gradient-to-b from-blue-50 to-blue-100 p-3 text-blue-800"
								>
									<div class="flex flex-row items-center gap-x-3">
										<LightbulbSolid size="md" class="shrink-0" />
										<div class="flex flex-col text-xs">
											<span class="font-bold"
												>Assistant responses may include inline URL citations</span
											>
											<span
												>When the assistant uses web search, URL citations may be included in its
												responses. Citations show the domain inline, and the web address and title
												in a popover. Members can click the inline citation to visit the source. You
												can interact with the example citation on the right.</span
											>
										</div>
									</div>
									<div class="flex flex-row items-center gap-x-3">
										<WebSourceChip
											source={{
												url: 'https://openai.com/index/gpt-5-1/',
												type: 'url',
												title: 'GPT-5.1: A smarter, more conversational ChatGPT'
											}}
											type="chip"
										/>
									</div>
								</div>
							</div>

							<hr />

							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_reasoning_summaries"
									name="hide_reasoning_summaries"
									disabled={preventEdits}
									bind:checked={hideReasoningSummaries}
									><div class="flex flex-row gap-1">
										<div>Hide Reasoning Summaries from Members</div>
									</div></Checkbox
								>
								<Helper
									>Control whether members can see summaries of the assistant's reasoning process.
									In some cases, this material may contain sensitive information or insights about
									the assistant's internal logic or prompt. When checked, members will not see the
									reasoning summaries. Moderators can always review reasoning summaries. <b
										>This setting will only apply to Chat Mode reasoning models.</b
									></Helper
								>
							</div>
							<hr />

							<div class="col-span-2 mb-1">
								<Checkbox
									id="hide_mcp_server_call_details"
									name="hide_mcp_server_call_details"
									disabled={preventEdits}
									bind:checked={hideMCPServerCallDetails}
									><div class="flex flex-row gap-1">
										<div>Hide MCP Server call details from Members</div>
									</div></Checkbox
								>
								<Helper
									>Control whether members can see MCP Server call details. In some cases, this
									material may contain sensitive information or insights about the assistant's
									internal logic or prompt. When checked, members will see when the assistant makes
									calls to an MCP Server, including which tools are called, but will not see
									detailed payloads or responses. Moderators can always review MCP Server call
									details. <b
										>This setting will only apply to Chat Mode models with the MCP Server tool
										enabled.</b
									></Helper
								>
							</div>
							<hr />
						{/if}

						{#if supportsTemperature && !isLectureMode}
							<div class="flex flex-col">
								<Label for="temperature">Temperature</Label>
								{#if interactionMode === 'voice'}
									<Helper class="pb-1"
										>Select the model's "temperature," a setting from 0.6 to 1.2 that controls how
										creative or predictable the assistant's responses are. For audio models, a
										temperature of 0.8 is highly recommended for best performance. You can change
										this setting anytime.</Helper
									>
								{:else}
									<Helper class="pb-1"
										>Select the model's "temperature," a setting from 0 to 2 that controls how
										creative or predictable the assistant's responses are. For reliable, focused
										answers, choose a temperature closer to 0.2. For more varied or creative
										responses, try a setting closer to 1. Avoid setting the temperature much above 1
										unless you need very experimental responses, as it may lead to less predictable
										and more random answers.</Helper
									>
								{/if}
							</div>
							<div class="mt-2 flex flex-row justify-between">
								<div class="flex flex-row items-center gap-1 text-sm">
									<ArrowLeftOutline />
									<div>More focused</div>
								</div>
								<Badge
									class="flex shrink-0 flex-row items-center gap-x-2 rounded-md border border-sky-400 bg-gradient-to-b from-sky-100 to-sky-200 px-2 py-0.5 text-xs text-sky-800 normal-case"
								>
									<div>Temperature: {temperatureValue.toFixed(1)}</div>
								</Badge>
								<div class="flex flex-row items-center gap-1 text-sm">
									<div>More creative</div>
									<ArrowRightOutline />
								</div>
							</div>
							{#if interactionMode !== 'voice'}
								<Range
									id="temperature"
									name="temperature"
									min={minChatTemperature}
									max={maxChatTemperature}
									bind:value={temperatureValue}
									step="0.1"
									disabled={preventEdits}
									onchange={checkForLargeTemperatureChat}
									class="appearance-auto"
								/>
								<div class="mx-2 grid grid-cols-20 gap-0">
									<button
										type="button"
										class="col-span-4 ml-1 flex flex-col items-center justify-start border-0 bg-transparent"
										onclick={() => {
											temperatureValue = defaultChatTemperature;
											_temperatureValue = defaultChatTemperature;
										}}
										onkeydown={(e) => {
											if (e.key === 'Enter' || e.key === ' ') {
												temperatureValue = defaultChatTemperature;
												_temperatureValue = defaultChatTemperature;
											}
										}}
									>
										<HeartSolid class="max-w-fit text-gray-500" />
										<div class="mx-10 mt-1 text-center text-sm text-wrap">
											Default (recommended)
										</div>
									</button>
									<button
										type="button"
										class="col-span-4 col-start-6 flex flex-col items-center justify-start border-0 bg-transparent"
										onclick={() => {
											temperatureValue = 0.7;
											_temperatureValue = 0.7;
										}}
										onkeydown={(e) => {
											if (e.key === 'Enter' || e.key === ' ') {
												temperatureValue = 0.7;
												_temperatureValue = 0.7;
											}
										}}
									>
										<LightbulbSolid class="max-w-fit text-gray-500" />
										<div class="mx-10 mt-1 text-center text-sm text-wrap">
											Great for creative tasks and brainstorming
										</div>
									</button>
									<div
										class="col-span-9 col-start-12 -mr-2 -ml-2 h-6 h-fit rounded-md border border-amber-400 bg-gradient-to-b from-amber-100 to-amber-200 py-1 text-center text-sm text-amber-800"
									>
										Output may be unpredictable
									</div>
								</div>
							{:else}
								<Range
									id="temperature"
									name="temperature"
									min={minAudioTemperature}
									max={maxAudioTemperature}
									bind:value={temperatureValue}
									step="0.1"
									disabled={preventEdits}
									onchange={checkForLargeTemperatureAudio}
									class="appearance-auto"
								/>
								<div class="mx-2 grid grid-cols-6 gap-0">
									<button
										type="button"
										class="col-span-4 ml-1 flex flex-col items-center justify-start border-0 bg-transparent"
										onclick={() => {
											temperatureValue = defaultAudioTemperature;
											_temperatureValue = defaultAudioTemperature;
										}}
										onkeydown={(e) => {
											if (e.key === 'Enter' || e.key === ' ') {
												temperatureValue = defaultAudioTemperature;
												_temperatureValue = defaultAudioTemperature;
											}
										}}
									>
										<HeartSolid class="max-w-fit text-gray-500" />
										<div class="mx-10 mt-1 text-center text-sm text-wrap">
											Default (highly recommended)
										</div>
									</button>
								</div>
							{/if}
						{/if}
						{#if supportsReasoning && !isLectureMode}
							<div class="flex flex-col">
								<Label for="reasoning-effort">Reasoning effort</Label>
								<Helper class="pb-1"
									>Select your desired reasoning effort, which gives the model guidance on how much
									time it should spend "reasoning" before creating a response to the prompt. {#if reasoningEffortLabels.length !== 1}You
										can specify one of
										{#each reasoningEffortLabels as label, idx (label)}
											<span class="font-mono">{label}</span>{idx < reasoningEffortLabels.length - 1
												? ','
												: ''}
										{/each}for this setting, where <span class="font-mono">low</span> will favor
										speed, and
										<span class="font-mono">high</span>
										will favor more complete reasoning at the cost of slower responses. The default value
										is <span class="font-mono">{defaultReasoningLabel}</span>.{/if}</Helper
								>
								{#if reasoningEffortLabels.length === 1}
									<div
										class="mt-2 flex flex-row items-center justify-between gap-x-4 rounded-lg border border-amber-400 bg-gradient-to-b from-amber-50 to-amber-100 p-3 text-amber-800"
									>
										<div class="flex flex-row items-center gap-x-3">
											<LightbulbSolid size="md" class="shrink-0" />
											<div class="flex flex-col text-xs">
												<span class="font-bold"
													>This model only supports <span class="font-mono"
														>{reasoningEffortLabels[0]}</span
													> reasoning effort</span
												>
												<span
													>For other models, you can control how long the model spends thinking
													using this setting.</span
												>
											</div>
										</div>
									</div>
								{/if}
							</div>
							{#if reasoningEffortLabels.length !== 1}
								<Range
									id="reasoning-effort"
									name="reasoning-effort"
									min={reasoningEffortMin}
									max={reasoningEffortMax}
									bind:value={reasoningEffortValue}
									step="1"
									disabled={preventEdits}
									class="appearance-auto"
								/>
								<div class="mt-2 flex flex-row justify-between">
									{#if reasoningEffortLabels.length < 4}
										{#each reasoningEffortLabels as label (label)}
											<p class="text-sm">{label}</p>
										{/each}
									{:else if supportsNoneReasoningEffort}
										<p class="text-sm">{reasoningEffortLabels[0]}</p>
										<p class="ml-4 text-sm">{reasoningEffortLabels[1]}</p>
										<p class="ml-2 text-sm">{reasoningEffortLabels[2]}</p>
										<p class="text-sm">{reasoningEffortLabels[3]}</p>
									{:else}
										<p class="text-sm">{reasoningEffortLabels[0]}</p>
										<p class="-ml-2 text-sm">{reasoningEffortLabels[1]}</p>
										<p class="ml-1 text-sm">{reasoningEffortLabels[2]}</p>
										<p class="text-sm">{reasoningEffortLabels[3]}</p>
									{/if}
								</div>
							{/if}
						{/if}
						{#if supportsVerbosity && !isLectureMode}
							<div class="flex flex-col">
								<Label for="verbosity">Verbosity</Label>
								<Helper class="pb-1"
									>Select your desired verbosity. Verbosity determines how many output tokens are
									generated. Lowering the number of tokens reduces overall latency. While the
									model's reasoning approach stays mostly the same, the model finds ways to answer
									more concisely—which can either improve or diminish answer quality, depending on
									your use case. Here are some scenarios for both ends of the verbosity spectrum:
									<ol class="ml-7 list-disc">
										<li class="my-1">
											<span class="font-medium">High verbosity:</span> Use when you need the model to
											provide thorough explanations of documents or perform extensive code refactoring.
										</li>
										<li class="my-1">
											<span class="font-medium">Low verbosity:</span> Best for situations where you want
											concise answers or simple code generation, such as SQL queries.
										</li>
									</ol>
									Models before GPT-5 have used medium verbosity by default. With GPT-5, this option is
									configurable as one of<span class="font-mono">high</span>,
									<span class="font-mono">medium</span>, or <span class="font-mono">low</span>. When
									generating code, <span class="font-mono">medium</span> and
									<span class="font-mono">high</span>
									verbosity levels yield longer, more structured code with inline explanations, while
									<span class="font-mono">low</span>
									verbosity produces shorter, more concise code with minimal commentary. The default value
									is
									<span class="font-mono">medium</span>.</Helper
								>
							</div>
							<Range
								id="verbosity"
								name="verbosity"
								min="0"
								max="2"
								bind:value={verbosityValue}
								step="1"
								disabled={preventEdits}
								class="appearance-auto"
							/>
							<div class="mt-2 flex flex-row justify-between">
								<p class="text-sm">low</p>
								<p class="text-sm">medium</p>
								<p class="text-sm">high</p>
							</div>
						{/if}
						<hr />

						{#if !data.isCreating || isLectureMode}
							<div class="col-span-2 mb-1">
								<span
									class="block text-sm font-medium text-gray-900 rtl:text-right dark:text-gray-300"
									>Assistant Version: {assistantVersion === 3
										? 'Next-Gen Assistants'
										: assistantVersion
											? 'Classic Assistants'
											: 'No Version Information'}</span
								>
								{#if isLectureMode}
									<Helper class="pb-1"
										>Lecture video mode assistants always use Next-Gen Assistants.</Helper
									>
								{:else}
									<Helper class="pb-1"
										>Shows which version of Assistants you’re using. Next-Gen Assistants are the
										next generation of PingPong Assistants. They're designed to enable additional
										capabilities and improve reliability. Most new Assistants you create will
										automatically use this Next-Gen version. Existing Classic Assistants will
										continue to work just as expected and will be upgraded to Next-Gen in the future
										so you can take advantage of the latest improvements.</Helper
									>
								{/if}
								{#if canSwitchAssistantVersion}
									<div class="mt-4 flex flex-row gap-1.5">
										<DropdownBadge
											extraClasses="border-amber-400 from-amber-100 to-amber-200 text-amber-800 py-0 px-1"
											><span slot="name">Preview</span></DropdownBadge
										>
										<div class="text-sm font-medium text-gray-900">
											{#if (assistantVersion === 3 && convertToNextGen === null) || (assistantVersion === 2 && convertToNextGen === false)}Revert
												back to the previous generation of Voice Mode assistants{:else}Switch to the
												new generation of Voice Mode assistants{/if}
										</div>
									</div>
									<Helper class="mt-1"
										>Help us test the next generation of Voice Mode assistants, designed to enable
										additional capabilities and improve reliability. During the preview period,
										Next-Gen voice assistants may be unstable and result in missing or incomplete
										transcripts. You can switch back to the previous assistant generation at any
										time.</Helper
									>
									<div class="mt-2 flex flex-row items-center gap-2">
										<Button
											type="button"
											size="xs"
											color="light"
											class="w-fit"
											disabled={preventEdits || convertToNextGen !== null}
											onclick={switchAssistantVersion}
											>{convertToNextGen === true
												? 'Converts to Next-Gen on Save'
												: convertToNextGen === false
													? 'Switches to Classic on Save'
													: assistantVersion === 3
														? 'Switch Back to Classic'
														: 'Convert to Next-Gen'}</Button
										>
									</div>
								{/if}
							</div>
						{:else}
							<div class="col-span-2 mb-1">
								<Checkbox
									id="create_classic_assistant"
									name="create_classic_assistant"
									class={isClassicRequired ? 'text-gray-400 contrast-50 grayscale' : ''}
									disabled={preventEdits || isClassicRequired}
									checked={createClassicAssistant}
									onchange={() => {
										createClassicAssistantByProviderOrUser =
											!createClassicAssistantByProviderOrUser;
									}}
									><div class="flex flex-wrap gap-1">
										<div>Create Classic Assistant</div>
										{#if data?.enforceClassicAssistants}<div>&middot;</div>
											<div>Next-Gen Assistants unavailable for your AI Provider</div>{/if}
										{#if interactionMode === 'voice'}<div>&middot;</div>
											<div>Voice Mode requires Classic Assistants</div>{/if}
									</div></Checkbox
								>
								<Helper
									>Control whether to use the previous generation of Assistants. When checked,
									you'll create a Classic Assistant instead of a Next-Gen Assistant.<br /><br
									/>Next-Gen Assistants are the next generation of PingPong Assistants. They're
									designed to enable additional capabilities and improve reliability. Most new
									Assistants you create will automatically use this Next-Gen version. Existing
									Classic Assistants will continue to work just as expected and will be upgraded to
									Next-Gen in the future so you can take advantage of the latest improvements.</Helper
								>
							</div>
						{/if}

						<hr />

						<div class="col-span-2 mb-1">
							<Label for="notes">Notes</Label>
							<Helper class="pb-1"
								>Add any notes here. This information is <strong>not</strong> shown to users, and intended
								for documentation.</Helper
							>
							<Textarea
								id="notes"
								name="notes"
								class="field-sizing-content min-h-32"
								bind:value={notes}
								disabled={preventEdits}
							/>
						</div>
					</div>
				</AccordionItem>
			</Accordion>
		</div>

		<input type="hidden" name="assistantId" value={assistant?.id} />

		<div class="col-span-2 mt-4 flex items-center border-t pt-4">
			<Button
				pill
				class="border border-orange bg-orange text-white hover:bg-orange-dark"
				type="submit"
				disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}>Save</Button
			>
			<Button
				disabled={$loading || uploadingFSPrivate || uploadingCIPrivate}
				href={`/group/${data.class.id}/assistant`}
				color="red"
				pill
				class="ml-4 rounded-full border border-blue-dark-40 bg-blue-light-50 text-blue-dark-50 hover:bg-blue-light-40"
				>Cancel</Button
			>
		</div>
	</form>
</div>
