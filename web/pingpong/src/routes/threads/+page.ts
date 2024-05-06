import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, url }) => {
  const searchParams = url.searchParams;
  const classId = searchParams.get('class_id');
  const privThreads = searchParams.get('private');
  const search: api.GetAllThreadsOpts = {};

  if (classId && classId !== '0') {
    search.class_id = parseInt(classId);
  }

  if (privThreads) {
    search.private = privThreads === 'true';
  }

  const threadArchive = await api.getAllThreads(fetch, search);
  return {
    threadArchive
  };
};
