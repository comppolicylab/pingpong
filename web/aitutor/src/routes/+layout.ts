import {goto} from "$app/navigation";
import {redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";
import * as api from "$lib/api";

const LOGIN = "/login";
const HOME = "/";

/**
 * Load the current user and redirect if they are not logged in.
 */
export async function load({fetch, url, params}: { fetch: api.Fetcher, url: URL, params: { threadId?: string, classId?: string } }) {
  // Fetch the current user
  const me = await api.me(fetch);
  const authed = me.status === "valid";

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
    classes: [],
    threads: [],
    institutions: [],
  };

  if (authed) {
    const promises = new Map<keyof typeof additionalState, Promise<any>>();

    promises.set("classes", api.getMyClasses(fetch).then(({classes}) => classes));
    const classId = params.classId ? parseInt(params.classId, 10) : null;
    if (classId) {
      promises.set("threads", api.getClassThreads(fetch, classId).then(({threads}) => threads));
    } else {
      promises.set("threads", Promise.resolve([]));
    }

    if (me.user.super_admin) {
      promises.set("institutions", api.getInstitutions(fetch).then(({institutions}) => institutions));
    } else {
      promises.set("institutions", Promise.resolve([]));
    }

    const entries = Array.from(promises.entries());
    const keys = entries.map(([key]) => key);
    const values = entries.map(([, value]) => value);
    const results = await Promise.all(values);

    for (let i = 0; i < keys.length; i++) {
      additionalState[keys[i]] = results[i];
    }
  }

  return {
    me,
    ...additionalState,
  };
}
