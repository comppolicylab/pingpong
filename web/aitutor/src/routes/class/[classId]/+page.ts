import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const [threads, class_] = await Promise.all([
    api.getClassThreads(fetch, params.classId),
    api.getClass(fetch, params.classId),
  ]);
  return {threads, "class": class_};
}
