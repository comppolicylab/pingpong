import type { PageLoad } from './$types';
import type {
	Assistant,
	AssistantFiles,
	AssistantModel,
	AssistantDefaultPrompt,
	MCPServerToolInput,
	LectureVideoAssistantEditorPolicy as LectureVideoEditorPolicy,
	LectureLessonEditorConfig,
	LectureVideoConfigResponse,
	LectureSlideConfigResponse,
	Error as ApiError
} from '$lib/api';
import {
	getAssistantFiles,
	getAssistantMCPServers,
	getAssistantLectureVideoConfig,
	getAssistantLectureSlideConfig,
	getLectureVideoEditorPolicy,
	getLectureLessonEditorConfig,
	expandResponse,
	getModels
} from '$lib/api';
import { modelsPromptsStore } from '$lib/stores/general';
import { get } from 'svelte/store';

const DEFAULT_LECTURE_VIDEO_EDITOR_POLICY: LectureVideoEditorPolicy = {
	show_mode_in_assistant_editor: false,
	can_select_mode_in_assistant_editor: false,
	message: null
};

async function ensureModels(
	fetchFn: typeof fetch,
	classId: number
): Promise<{
	models: AssistantModel[];
	defaultPrompts: AssistantDefaultPrompt[];
	enforceClassicAssistants: boolean;
}> {
	const cache = get(modelsPromptsStore)[classId];

	if (cache) {
		return {
			models: cache.models,
			defaultPrompts: cache.default_prompts ?? [],
			enforceClassicAssistants: cache.enforce_classic_assistants ?? false
		};
	}

	const modelsResponse = await getModels(fetchFn, classId).then(expandResponse);
	if (modelsResponse.error) {
		return {
			models: [],
			defaultPrompts: [],
			enforceClassicAssistants: false
		};
	}

	const models = modelsResponse.data.models;
	const defaultPrompts = modelsResponse.data.default_prompts ?? [];
	const enforceClassicAssistants = modelsResponse.data.enforce_classic_assistants ?? false;

	modelsPromptsStore.update((m) => ({
		...m,
		[classId]: {
			models,
			default_prompts: defaultPrompts,
			enforce_classic_assistants: enforceClassicAssistants
		} as (typeof m)[number]
	}));

	return {
		models,
		defaultPrompts,
		enforceClassicAssistants
	};
}

async function loadAssistantFilesOrNull(
	fetchFn: typeof fetch,
	classId: number,
	assistantId: number
): Promise<AssistantFiles | null> {
	const assistantFilesResponse = await getAssistantFiles(fetchFn, classId, assistantId).then(
		expandResponse
	);
	return assistantFilesResponse.error ? null : assistantFilesResponse.data.files;
}

async function loadAssistantMCPServers(
	fetchFn: typeof fetch,
	classId: number,
	assistantId: number
): Promise<MCPServerToolInput[]> {
	const response = await getAssistantMCPServers(fetchFn, classId, assistantId).then(expandResponse);
	return response.error ? [] : response.data.mcp_servers;
}

async function loadAssistantLectureVideoConfig(
	fetchFn: typeof fetch,
	classId: number,
	assistantId: number
): Promise<{
	lectureVideoConfig: LectureVideoConfigResponse | null;
	lectureVideoConfigLoadError: (ApiError & { $status: number }) | null;
}> {
	const response = await getAssistantLectureVideoConfig(fetchFn, classId, assistantId).then(
		expandResponse
	);
	return response.error
		? {
				lectureVideoConfig: null,
				lectureVideoConfigLoadError: {
					$status: response.$status,
					...response.error
				}
			}
		: {
				lectureVideoConfig: response.data,
				lectureVideoConfigLoadError: null
			};
}

async function loadAssistantLectureSlideConfig(
	fetchFn: typeof fetch,
	classId: number,
	assistantId: number
): Promise<{
	lectureSlideConfig: LectureSlideConfigResponse | null;
	lectureSlideConfigLoadError: (ApiError & { $status: number }) | null;
}> {
	const response = await getAssistantLectureSlideConfig(fetchFn, classId, assistantId).then(
		expandResponse
	);
	return response.error
		? {
				lectureSlideConfig: null,
				lectureSlideConfigLoadError: {
					$status: response.$status,
					...response.error
				}
			}
		: {
				lectureSlideConfig: response.data,
				lectureSlideConfigLoadError: null
			};
}

async function loadLectureVideoEditorPolicy(
	fetchFn: typeof fetch,
	classId: number
): Promise<LectureVideoEditorPolicy> {
	const response = await getLectureVideoEditorPolicy(fetchFn, classId).then(expandResponse);
	return response.error ? DEFAULT_LECTURE_VIDEO_EDITOR_POLICY : response.data;
}

async function loadLectureLessonEditorConfig(
	fetchFn: typeof fetch,
	classId: number
): Promise<LectureLessonEditorConfig | null> {
	const response = await getLectureLessonEditorConfig(fetchFn, classId).then(expandResponse);
	return response.error || !response.data.lecture_lesson_available ? null : response.data;
}

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch, parent }) => {
	const classId = parseInt(params.classId, 10);
	const isCreating = params.assistantId === 'new';
	const parentData = await parent();
	const [
		{ models, defaultPrompts, enforceClassicAssistants },
		lectureVideoPolicy,
		lectureLessonEditorConfig
	] = await Promise.all([
		ensureModels(fetch, classId),
		loadLectureVideoEditorPolicy(fetch, classId),
		loadLectureLessonEditorConfig(fetch, classId)
	]);

	let assistant: Assistant | null = null;
	let assistantFiles: AssistantFiles | null = null;
	let mcpServers: MCPServerToolInput[] = [];
	let lectureVideoConfig: LectureVideoConfigResponse | null = null;
	let lectureVideoConfigLoadError: (ApiError & { $status: number }) | null = null;
	let lectureSlideConfig: LectureSlideConfigResponse | null = null;
	let lectureSlideConfigLoadError: (ApiError & { $status: number }) | null = null;

	if (!isCreating) {
		const assistants = parentData.assistants ?? [];
		const id = parseInt(params.assistantId, 10);
		assistant = assistants.find((a) => a.id === id) ?? null;

		if (assistant) {
			const [files, servers] = await Promise.all([
				loadAssistantFilesOrNull(fetch, classId, assistant.id),
				loadAssistantMCPServers(fetch, classId, assistant.id)
			]);
			assistantFiles = files;
			mcpServers = servers;
			if (assistant.interaction_mode === 'lecture_video') {
				const lectureVideoConfigResult = await loadAssistantLectureVideoConfig(
					fetch,
					classId,
					assistant.id
				);
				lectureVideoConfig = lectureVideoConfigResult.lectureVideoConfig;
				lectureVideoConfigLoadError = lectureVideoConfigResult.lectureVideoConfigLoadError;
			} else if (assistant.interaction_mode === 'lecture_slides') {
				const lectureSlideConfigResult = await loadAssistantLectureSlideConfig(
					fetch,
					classId,
					assistant.id
				);
				lectureSlideConfig = lectureSlideConfigResult.lectureSlideConfig;
				lectureSlideConfigLoadError = lectureSlideConfigResult.lectureSlideConfigLoadError;
			}
		}
	}

	const effectiveLectureVideoPolicy =
		assistant?.interaction_mode === 'lecture_video' ||
		assistant?.interaction_mode === 'lecture_slides'
			? {
					...lectureVideoPolicy,
					show_mode_in_assistant_editor: true
				}
			: lectureVideoPolicy;

	return {
		isCreating,
		assistantId: isCreating ? null : parseInt(params.assistantId, 10),
		assistant,
		selectedFileSearchFiles: assistantFiles ? assistantFiles.file_search_files : [],
		selectedCodeInterpreterFiles: assistantFiles ? assistantFiles.code_interpreter_files : [],
		mcpServers,
		models,
		defaultPrompts,
		enforceClassicAssistants,
		lectureLessonEditorConfig,
		lectureVideoPolicy: effectiveLectureVideoPolicy,
		lectureVideoConfig,
		lectureVideoConfigLoadError,
		lectureSlideConfig,
		lectureSlideConfigLoadError,
		statusComponents: parentData.statusComponents ?? {}
	};
};
