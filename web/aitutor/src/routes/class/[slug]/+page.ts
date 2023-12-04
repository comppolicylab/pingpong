import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const [threads, class_] = await Promise.all([
    api.getClassThreads(fetch, params.slug),
    api.getClass(fetch, params.slug),
  ]);
  return {threads, "class": class_};
}
