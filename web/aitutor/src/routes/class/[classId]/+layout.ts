import * as api from "$lib/api";

export async function load({ fetch, params }) {
  const class_ = await api.getClass(fetch, params.classId);
  return {"class": class_};
}
