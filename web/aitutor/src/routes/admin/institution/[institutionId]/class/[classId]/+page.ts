import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const classData = await api.getClass(fetch, params.classId);
  const assistants = await api.getAssistants(fetch, params.classId);
  const files = await api.getClassFiles(fetch, params.classId);
  return {
    "class": classData,
    assistants,
    files,
    "institutionId": params.institutionId,
  }
}
