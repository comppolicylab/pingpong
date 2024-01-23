import * as api from "$lib/api";
import type { PageLoad } from "./$types";

/**
 * Load additional data needed for managing the class.
 */
export const load: PageLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const {api_key}= await api.getApiKey(fetch, classId);
  const {users} = await api.getClassUsers(fetch, classId);

  let models = [];
  if (api_key) {
    const modelResponse = await api.getModels(fetch, classId);
    models = modelResponse.models;
  }

  return {
    models,
    apiKey: api_key || '',
    classUsers: users,
  };
}
