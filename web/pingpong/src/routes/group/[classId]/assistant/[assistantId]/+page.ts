import type { PageLoad } from './$types';
import type {
	Assistant,
	AssistantFiles,
	AssistantModel,
	AssistantDefaultPrompt,
	MCPServerToolInput,
	LectureVideoSummary,
	LectureVideoManifest,
	LectureVideoAssistantEditorPolicy as LectureVideoEditorPolicy
} from '$lib/api';
import { getAssistantFiles, getAssistantMCPServers, expandResponse, getModels } from '$lib/api';
import { modelsPromptsStore } from '$lib/stores/general';
import { get } from 'svelte/store';

type LectureVideoConfigResponse = {
	lecture_video: LectureVideoSummary;
	lecture_video_manifest: LectureVideoManifest;
	voice_id: string;
};

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
	lectureVideoPolicy: LectureVideoEditorPolicy;
}> {
	const cache = get(modelsPromptsStore)[classId];
	if (cache) {
		const cacheWithPolicy = cache as typeof cache & {
			lecture_video?: LectureVideoEditorPolicy;
		};
		return {
			models: cache.models,
			defaultPrompts: cache.default_prompts ?? [],
			enforceClassicAssistants: cache.enforce_classic_assistants ?? false,
			lectureVideoPolicy: cacheWithPolicy.lecture_video ?? DEFAULT_LECTURE_VIDEO_EDITOR_POLICY
		};
	}

	const modelsResponse = await getModels(fetchFn, classId).then(expandResponse);
	const models = modelsResponse.error ? [] : modelsResponse.data.models;
	const defaultPrompts = modelsResponse.error ? [] : (modelsResponse.data.default_prompts ?? []);
	const enforceClassicAssistants = modelsResponse.error
		? false
		: (modelsResponse.data.enforce_classic_assistants ?? false);
	const lectureVideoPolicy = modelsResponse.error
		? DEFAULT_LECTURE_VIDEO_EDITOR_POLICY
		: ((
				modelsResponse.data as typeof modelsResponse.data & {
					lecture_video?: LectureVideoEditorPolicy;
				}
			).lecture_video ?? DEFAULT_LECTURE_VIDEO_EDITOR_POLICY);

	modelsPromptsStore.update((m) => ({
		...m,
		[classId]: {
			models,
			default_prompts: defaultPrompts,
			enforce_classic_assistants: enforceClassicAssistants,
			lecture_video: lectureVideoPolicy
		} as (typeof m)[number]
	}));

	return { models, defaultPrompts, enforceClassicAssistants, lectureVideoPolicy };
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
): Promise<LectureVideoConfigResponse | null> {
	try {
		const response = await fetchFn(
			`/api/v1/class/${classId}/assistant/${assistantId}/lecture-video/config`
		);
		if (!response.ok) {
			return null;
		}
		return (await response.json()) as LectureVideoConfigResponse;
	} catch {
		return null;
	}
}

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch, parent }) => {
	const classId = parseInt(params.classId, 10);
	const isCreating = params.assistantId === 'new';
	const parentData = await parent();
	const { models, defaultPrompts, enforceClassicAssistants, lectureVideoPolicy } =
		await ensureModels(fetch, classId);

	let assistant: Assistant | null = null;
	let assistantFiles: AssistantFiles | null = null;
	let mcpServers: MCPServerToolInput[] = [];
	let lectureVideoConfig: LectureVideoConfigResponse | null = null;

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
				lectureVideoConfig = await loadAssistantLectureVideoConfig(fetch, classId, assistant.id);
			}
		}
	}

	const effectiveLectureVideoPolicy =
		assistant?.interaction_mode === 'lecture_video'
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
		lectureVideoPolicy: effectiveLectureVideoPolicy,
		lectureVideoConfig,
		statusComponents: parentData.statusComponents ?? {}
	};
};
