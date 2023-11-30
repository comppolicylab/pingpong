import {goto} from "$app/navigation";
import {redirect} from "@sveltejs/kit";
import {browser} from "$app/environment";
import * as api from "$lib/api";

const LOGIN = "/login";
const HOME = "/";

/**
 * Load the current user and redirect if they are not logged in.
 */
export async function load({fetch, url}: { fetch: api.Fetcher, url: URL }) {
  // Fetch the current user
  const me = await api.me(fetch);

  if (url.pathname === LOGIN) {
    // If the user is logged in, go to the home page.
    if (me.status === "valid") {
      if (browser) {
        goto(HOME);
      } else {
        throw redirect(302, HOME);
      }
    }
  } else {
    // If the user is not logged in, go to the login page.
    if (me.status !== "valid") {
      if (browser) {
        goto(LOGIN);
      } else {
        throw redirect(302, LOGIN);
      }
    }
  }

  return {
    me,
  };
}
