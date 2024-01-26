import * as api from "$lib/api";
import {goto} from "$app/navigation";
import {error, redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";

export async function load({ fetch, params }) {
  const classData = await api.getClass(fetch, params.classId);
  if (classData.$status >= 300) {
    throw error(classData.$status, classData.detail || "Unknown error");
  }
  const {creators: assistantCreators, assistants} = await api.getAssistants(fetch, params.classId);
  const {files} = await api.getClassFiles(fetch, params.classId);

  return {
    hasAssistants: !!assistants && assistants.length > 0,
    hasBilling: !!classData?.api_key,
    "class": classData,
    assistants,
    assistantCreators,
    files,
  }
}
