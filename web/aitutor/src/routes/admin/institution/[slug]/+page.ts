import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const institution = await api.getInstitution(fetch, params.slug);
  const {classes} = await api.getClasses(fetch, params.slug);
  return {
    institution,
    classes,
  }
}
