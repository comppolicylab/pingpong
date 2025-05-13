import type { PageLoad } from './$types';
import type { Assistant, AssistantFiles, AssistantModel, AssistantDefaultPrompt } from '$lib/api';
import { getAssistantFiles, expandResponse, getModels } from '$lib/api';
import { modelsPromptsStore } from '$lib/stores/general';
import { get } from 'svelte/store';

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch, parent }) => {
  const isCreating = params.assistantId === 'new';
  let assistant: Assistant | null = null;
  let assistantFiles: AssistantFiles | null = null;
  let models: AssistantModel[] = [];
  let defaultPrompts: AssistantDefaultPrompt[] = [];
  const allModelsDefaultPrompts = get(modelsPromptsStore);
  if (!isCreating) {
    const parentData = await parent();
    assistant =
      parentData.assistants.find((a) => a.id === parseInt(params.assistantId, 10)) || null;

    if (!allModelsDefaultPrompts[parentData.class.id]) {
      if (assistant) {
        const [assistantFilesResponse, modelsResponse] = await Promise.all([
          getAssistantFiles(fetch, parentData.class.id, assistant.id).then(expandResponse),
          getModels(fetch, parentData.class.id).then(expandResponse)
        ]);
        assistantFiles = assistantFilesResponse.error ? null : assistantFilesResponse.data.files;
        models = modelsResponse.error ? [] : modelsResponse.data.models;
        defaultPrompts = modelsResponse.error ? [] : (modelsResponse.data.default_prompts ?? []);
        modelsPromptsStore.update((m) => ({
          ...m,
          [parentData.class.id]: { models, default_prompts: defaultPrompts }
        }));
      } else {
        const modelsResponse = await getModels(fetch, parentData.class.id).then(expandResponse);
        models = modelsResponse.error ? [] : modelsResponse.data.models;
        defaultPrompts = modelsResponse.error ? [] : (modelsResponse.data.default_prompts ?? []);
        modelsPromptsStore.update((m) => ({
          ...m,
          [parentData.class.id]: { models, default_prompts: defaultPrompts }
        }));
      }
    } else {
      if (assistant) {
        const assistantFilesResponse = await getAssistantFiles(
          fetch,
          parentData.class.id,
          assistant.id
        ).then(expandResponse);
        assistantFiles = assistantFilesResponse.error ? null : assistantFilesResponse.data.files;
      }
      const modelsAndDefaultPrompts = allModelsDefaultPrompts[parentData.class.id];
      models = modelsAndDefaultPrompts ? modelsAndDefaultPrompts.models : [];
      defaultPrompts = modelsAndDefaultPrompts
        ? (modelsAndDefaultPrompts.default_prompts ?? [])
        : [];
    }
  } else {
    const classId = parseInt(params.classId, 10);
    if (!allModelsDefaultPrompts[classId]) {
      const modelsResponse = await getModels(fetch, classId).then(expandResponse);
      models = modelsResponse.error ? [] : modelsResponse.data.models;
      defaultPrompts = modelsResponse.error ? [] : (modelsResponse.data.default_prompts ?? []);
      modelsPromptsStore.update((m) => ({
        ...m,
        [classId]: { models, default_prompts: defaultPrompts }
      }));
    } else {
      const modelsAndDefaultPrompts = allModelsDefaultPrompts[classId];
      models = modelsAndDefaultPrompts ? modelsAndDefaultPrompts.models : [];
      defaultPrompts = modelsAndDefaultPrompts
        ? (modelsAndDefaultPrompts.default_prompts ?? [])
        : [];
    }
  }

  return {
    isCreating,
    assistantId: isCreating ? null : parseInt(params.assistantId, 10),
    assistant,
    selectedFileSearchFiles: assistantFiles ? assistantFiles.file_search_files : [],
    selectedCodeInterpreterFiles: assistantFiles ? assistantFiles.code_interpreter_files : [],
    models,
    defaultPrompts
  };
};
