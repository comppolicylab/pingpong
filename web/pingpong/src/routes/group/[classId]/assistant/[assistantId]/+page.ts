import type { PageLoad } from './$types';
import type { Assistant, AssistantFiles, AssistantModel, AssistantDefaultPrompt } from '$lib/api';
import { getAssistantFiles, expandResponse, getModels } from '$lib/api';
import { modelsPromptsStore } from '$lib/stores/general';
import { get } from 'svelte/store';

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
  const models = modelsResponse.error ? [] : modelsResponse.data.models;
  const defaultPrompts = modelsResponse.error ? [] : (modelsResponse.data.default_prompts ?? []);
  const enforceClassicAssistants = modelsResponse.error
    ? false
    : (modelsResponse.data.enforce_classic_assistants ?? false);

  modelsPromptsStore.update((m) => ({
    ...m,
    [classId]: {
      models,
      default_prompts: defaultPrompts,
      enforce_classic_assistants: enforceClassicAssistants
    }
  }));

  return { models, defaultPrompts, enforceClassicAssistants };
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

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch, parent }) => {
  const classId = parseInt(params.classId, 10);
  const isCreating = params.assistantId === 'new';
  const parentData = await parent();
  const { models, defaultPrompts, enforceClassicAssistants } = await ensureModels(fetch, classId);

  let assistant: Assistant | null = null;
  let assistantFiles: AssistantFiles | null = null;

  if (!isCreating) {
    const assistants = parentData.assistants ?? [];
    const id = parseInt(params.assistantId, 10);
    assistant = assistants.find((a) => a.id === id) ?? null;

    if (assistant) {
      assistantFiles = await loadAssistantFilesOrNull(fetch, classId, assistant.id);
    }
  }

  return {
    isCreating,
    assistantId: isCreating ? null : parseInt(params.assistantId, 10),
    assistant,
    selectedFileSearchFiles: assistantFiles ? assistantFiles.file_search_files : [],
    selectedCodeInterpreterFiles: assistantFiles ? assistantFiles.code_interpreter_files : [],
    models,
    defaultPrompts,
    enforceClassicAssistants,
    statusComponents: parentData.statusComponents ?? {}
  };
};
