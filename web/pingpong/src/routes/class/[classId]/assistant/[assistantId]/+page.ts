import type { PageLoad } from './$types';
import type { Assistant, AssistantFiles } from '$lib/api';
import { getAssistantFiles, expandResponse } from '$lib/api';

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ params, fetch, parent }) => {
  const isCreating = params.assistantId === 'new';
  let assistant: Assistant | null = null;
  let assistantFiles: AssistantFiles | null = null;
  if (!isCreating) {
    const parentData = await parent();
    assistant =
      parentData.assistants.find((a) => a.id === parseInt(params.assistantId, 10)) || null;

    if (assistant) {
      const assistantFilesResponse = await getAssistantFiles(
        fetch,
        parentData.class.id,
        assistant.id
      ).then(expandResponse);
      assistantFiles = assistantFilesResponse.error ? null : assistantFilesResponse.data.files;
    }
  }

  return {
    isCreating,
    assistantId: isCreating ? null : parseInt(params.assistantId, 10),
    assistant,
    selectedFileSearchFiles: assistantFiles
      ? assistantFiles.file_search_files.map((file) => file.file_id)
      : [],
    selectedCodeInterpreterFiles: assistantFiles
      ? assistantFiles.code_interpreter_files.map((file) => file.file_id)
      : []
  };
};
