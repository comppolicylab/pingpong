import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const institution = await api.getInstitution(fetch, params.institutionId);
  const {classes} = await api.getClasses(fetch, params.institutionId);
  return {
    institution,
    classes,
  }
}
