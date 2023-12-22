import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const {api_key}= await api.getApiKey(fetch, params.classId);
  return {
    apiKey: api_key || '',
  };
}
