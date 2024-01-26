import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const {api_key}= await api.getApiKey(fetch, params.classId);
  const {users} = await api.getClassUsers(fetch, params.classId);

  let models = [];
  if (api_key) {
    const modelResponse = await api.getModels(fetch, params.classId);
    models = modelResponse.models;
  }

  return {
    models,
    apiKey: api_key || '',
    classUsers: users,
  };
}
