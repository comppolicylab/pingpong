import * as api from "$lib/api";
import {goto} from "$app/navigation";
import {redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";

export async function load({ fetch, params }) {
  const classData = await api.getClass(fetch, params.classId);
  const {assistants} = await api.getAssistants(fetch, params.classId);
  const {files} = await api.getClassFiles(fetch, params.classId);

  // Make sure that the class is in the correct institution
  if (classData?.institution_id !== parseInt(params.institutionId, 10)) {
    if (browser) {
      goto("/");
    } else {
      throw redirect(307, "/");
    }
  }

  return {
    isConfigured: !!assistants && assistants.length > 0,
    "class": classData,
    assistants,
    files,
    "institutionId": params.institutionId,
  }
}
