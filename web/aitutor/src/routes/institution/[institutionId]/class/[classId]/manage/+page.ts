import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const {api_key}= await api.getApiKey(fetch, params.classId);
  console.log("API KEY", api_key)
  return {apiKey: api_key || ''};
}
