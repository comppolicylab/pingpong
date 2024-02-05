import { goto } from '$app/navigation';
import { redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import * as api from '$lib/api';
import type { Class, Institution, Thread } from '$lib/api';
import type { LayoutLoad } from './$types';

const LOGIN = '/login';
const HOME = '/';

/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ fetch, url, params }) => {
  // Fetch the current user
  const me = await api.me(fetch);
  const authed = me.status === 'valid';

  if (url.pathname === LOGIN) {
    // If the user is logged in, go to the home page.
    if (authed) {
      if (browser) {
        goto(HOME);
      } else {
        throw redirect(302, HOME);
      }
    }
  } else {
    // If the user is not logged in, go to the login page.
    if (!authed) {
      if (browser) {
        goto(LOGIN);
      } else {
        throw redirect(302, LOGIN);
      }
    }
  }

  // Fetch class / thread data (needed to render the sidebar)
  // TODO - should move this elsewhere? into shared store?
  const additionalState = {
    classes: [] as Class[],
    threads: [] as Thread[],
    institutions: [] as Institution[]
  };

  if (authed) {
    const classes = api.getMyClasses(fetch).then(({ classes }) => classes);
    let threads: Promise<Thread[]> = Promise.resolve([]);
    let institutions: Promise<Institution[]> = Promise.resolve([]);

    const classId = params.classId ? parseInt(params.classId, 10) : null;

    if (classId) {
      threads = api.getClassThreads(fetch, classId).then(({ threads }) => threads);
    }

    if (me.user.super_admin) {
      institutions = api.getInstitutions(fetch).then(({ institutions }) => institutions);
    }

    // After all requests have fired / returned, set the state.
    additionalState.classes = await classes;
    additionalState.threads = await threads;
    additionalState.institutions = await institutions;
  }

  return {
    me,
    ...additionalState
  };
};
