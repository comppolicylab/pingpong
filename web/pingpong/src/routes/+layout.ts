import { goto } from '$app/navigation';
import { redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import * as api from '$lib/api';
import { getClassesManager } from '$lib/stores/classes';
import { getThreadsManager } from '$lib/stores/threads';
import type { Institution } from '$lib/api';
import type { LayoutLoad } from './$types';
import { getInstitutionsManager } from '$lib/stores/institutions';

const LOGIN = '/login';
const HOME = '/';

/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ fetch, url, params }) => {
  // Fetch the current user
  const me = api.expandResponse(await api.me(fetch));
  if (me.error) {
    throw redirect(302, LOGIN);
  }

  const authed = me.data.status === 'valid';

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
  const threadsMgr = getThreadsManager(fetch);
  const additionalState = {
    classes: getClassesManager(fetch),
    threads: threadsMgr.get(null),
    institutions: getInstitutionsManager(fetch)
  };

  if (authed) {
    const classId = params.classId ? parseInt(params.classId, 10) : null;

    // Load the classes and institutions.
    // We guarantee they will be loaded when the app first loads,
    // and only reloaded when the relevant page is loaded.
    const forceReloadIndexes = !classId;
    additionalState.classes.load(forceReloadIndexes);
    additionalState.institutions.load(forceReloadIndexes);

    if (classId) {
      additionalState.threads = threadsMgr.get(classId);
    }
  }

  return {
    me: me.data,
    ...additionalState
  };
};
