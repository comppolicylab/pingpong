import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const classData = await api.getClass(fetch, params.classId);
  return {
    "class": classData,
  }
}
