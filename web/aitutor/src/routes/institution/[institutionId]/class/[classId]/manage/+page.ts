import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const {api_key}= await api.getApiKey(fetch, params.classId);
  const users = await api.getClassUsers(fetch, params.classId);
  console.log("USERS", users)
  return {
    apiKey: api_key || '',
  };
}
