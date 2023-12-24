import * as api from "$lib/api";
import {goto} from "$app/navigation";
import {redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";

export async function load({ fetch, params }) {
  const classData = await api.getClass(fetch, params.classId);
  const {my_assistants: myAssistants, class_assistants: classAssistants} = await api.getAssistants(fetch, params.classId);
  const {files} = await api.getClassFiles(fetch, params.classId);

  // Make sure that the class is in the correct institution
  if (classData?.institution_id !== parseInt(params.institutionId, 10)) {
    if (browser) {
      goto("/");
    } else {
      throw redirect(307, "/");
    }
  }

  // Dedupe the assistants
  const classAssistantsIds = classAssistants.map((a) => a.id);
  const assistants = [...classAssistants, ...myAssistants.filter((a) => !classAssistantsIds.includes(a.id))];

  return {
    hasAssistants: !!assistants && assistants.length > 0,
    hasBilling: !!classData?.api_key,
    "class": classData,
    assistants,
    myAssistants: myAssistants,
    classAssistants: classAssistants,
    files,
    "institutionId": params.institutionId,
  }
}
