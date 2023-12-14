import {goto} from "$app/navigation";
import {redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";
import * as api from "$lib/api";

const LOGIN = "/login";
const HOME = "/";

/**
 * Load the current user and redirect if they are not logged in.
 */
export async function load({fetch, url, params}: { fetch: api.Fetcher, url: URL, params: { institutionId?: string, classId?: string } }) {
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

  // Fetch the available institutions
  // TODO - should move this elsewhere? into shared store?
  const additionalState = {
    institutions: [],
    classes: [],
    threads: [],
  };

  if (authed) {
    const promises = [];
    promises.push(api.getInstitutions(fetch));
    const instId = params.institutionId;

    if (instId) {
      promises.push(api.getClasses(fetch, instId));
    }

    const classId = params.classId ? parseInt(params.classId, 10) : null;
    if (classId) {
      promises.push(api.getClass(fetch, classId));
      promises.push(api.getClassThreads(fetch, classId));
    }

    const results = await Promise.all(promises);
    additionalState.institutions = results[0].institutions;
    additionalState.classes = results[1]?.classes;
    additionalState.threads = results[2]?.threads;
  }

  return {
    me,
    ...additionalState,
  };
}
