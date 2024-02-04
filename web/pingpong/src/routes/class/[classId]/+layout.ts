import * as api from "$lib/api";
import {goto} from "$app/navigation";
import {error, redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";
import type {LayoutLoad} from "./$types";

/**
 * Load data needed for class layout.
 */
export const load: LayoutLoad = async ({ fetch, params }) => {
  const classId = parseInt(params.classId, 10);
  const classData = await api.getClass(fetch, classId);
  if (classData.$status >= 300) {
    throw error(classData.$status, classData.detail || "Unknown error");
  }
  const {creators: assistantCreators, assistants} = await api.getAssistants(fetch, classId);
  const {files} = await api.getClassFiles(fetch, classId);
  const uploadInfo = await api.getClassUploadInfo(fetch, classId);

  return {
    hasAssistants: !!assistants && assistants.length > 0,
    hasBilling: !!classData?.api_key,
    "class": classData,
    assistants,
    assistantCreators,
    files,
    uploadInfo,
  }
}
