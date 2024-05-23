import { goto } from '$app/navigation';
import { redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import * as api from '$lib/api';
import type { LayoutLoad } from './$types';

const LOGIN = '/login';
const HOME = '/';

/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ fetch, url }) => {
  // Fetch the current user
  const me = api.expandResponse(await api.me(fetch));
  if (me.error) {
    redirect(302, LOGIN);
  }

  const authed = me.data.status === 'valid';

  if (url.pathname === LOGIN) {
    // If the user is logged in, go to the home page.
    if (authed) {
      if (browser) {
        goto(HOME);
      } else {
        redirect(302, HOME);
      }
    }
  } else {
    // If the user is not logged in, go to the login page.
    if (!authed) {
      if (browser) {
        goto(LOGIN);
      } else {
        redirect(302, LOGIN);
      }
    }
  }

  let classes: api.Class[] = [];
  let threads: api.Thread[] = [];
  let institutions: api.Institution[] = [];
  let canCreateInstitution = false;
  if (authed) {
    [classes, threads, canCreateInstitution, institutions] = await Promise.all([
      api
        .getMyClasses(fetch)
        .then(api.explodeResponse)
        .then((c) => c.classes),
      api.getRecentThreads(fetch).then((t) => t.threads),
      api.grants(fetch, {
        canCreateInstitution: { target_type: 'root', target_id: 0, relation: 'can_create_institution' },
      }).then((g) => g.canCreateInstitution),
      api
      .getInstitutions(fetch, 'can_create_class')
      .then(api.explodeResponse)
      .then((i) => i.institutions),
    ]);
  }

  const admin = {
    canCreateInstitution,
    canCreateClass: institutions,
    showAdminPage: authed && (canCreateInstitution || institutions.length > 0),
  }

  return {
    me: me.data,
    authed,
    classes,
    threads,
    admin,
  };
};
