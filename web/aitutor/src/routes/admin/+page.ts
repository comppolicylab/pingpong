import * as api from "$lib/api";

export async function load({ fetch }) {
  const {institutions} = await api.getInstitutions(fetch);
  return {
    institutions,
  }
}
