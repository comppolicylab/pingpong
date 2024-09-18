import { redirect, error } from '@sveltejs/kit';
import * as api from '$lib/api';
import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { invalidateAll } from '$app/navigation';

const LOGIN = '/login';
const HOME = '/';
const ONBOARDING = '/onboarding';
const ABOUT = '/about';
const PRIVACY_POLICY = '/privacy-policy';
const EDU = '/eduaccess';
const LOGOUT = '/logout';

/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ fetch, url }) => {
  // Fetch the current user
  const me = api.expandResponse(await api.me(fetch));

  // If we can't even load `me` then the server is probably down.
  // Redirect to the login page if we're not already there, just
  // in case that will work. Otherwise, just show the error.
  if (me.error) {
    if (url.pathname !== LOGIN) {
      redirect(302, LOGIN);
    } else {
      const errorObject = (me.error || {}) as { $status: number; detail: string };
      const code = errorObject.$status || 500;
      const message = errorObject.detail || 'An unknown error occurred.';
      error(code, { message: `Error reaching the server: ${message}` });
    }
  }

  const authed = me.data.status === 'valid';
  const needsOnboarding = !!me.data?.user && (!me.data.user.first_name || !me.data.user.last_name);

  // If the page is public, don't redirect to the login page.
  let isPublicPage = false;

  if (url.pathname === LOGIN) {
    // If the user is logged in, go to the forward page.
    if (authed) {
      const destination = url.searchParams.get('forward') || HOME;
      redirect(302, destination);
    }
  } else {
    if (new Set([ABOUT, PRIVACY_POLICY, EDU, HOME]).has(url.pathname) && !authed) {
      isPublicPage = true;
      if (url.pathname === HOME) {
        // If the user is not logged in and tries to access the root path, go to the About page.
        redirect(302, ABOUT);
      }
    } else if (!authed && url.pathname !== LOGOUT) {
      const destination = encodeURIComponent(`${url.pathname}${url.search}`);
      redirect(302, `${LOGIN}?forward=${destination}`);
    } else {
      if (needsOnboarding && url.pathname !== ONBOARDING) {
        const destination = encodeURIComponent(`${url.pathname}${url.search}`);
        redirect(302, `${ONBOARDING}?forward=${destination}`);
      } else if (!needsOnboarding && url.pathname === ONBOARDING) {
        // Just in case someone tries to go to the onboarding page when they don't need to.
        const destination = url.searchParams.get('forward') || HOME;
        redirect(302, destination);
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
      api
        .grants(fetch, {
          canCreateInstitution: {
            target_type: 'root',
            target_id: 0,
            relation: 'can_create_institution'
          }
        })
        .then((g) => g.canCreateInstitution),
      api
        .getInstitutions(fetch, 'can_create_class')
        .then(api.explodeResponse)
        .then((i) => i.institutions)
    ]);
  }

  const admin = {
    canCreateInstitution,
    canCreateClass: institutions,
    showAdminPage: authed && (canCreateInstitution || institutions.length > 0)
  };

  return {
    isPublicPage,
    needsOnboarding,
    me: me.data,
    authed,
    classes,
    threads,
    admin
  };
};
