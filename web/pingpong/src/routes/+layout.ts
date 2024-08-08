import { redirect } from '@sveltejs/kit';
import * as api from '$lib/api';
import type { LayoutLoad } from './$types';

const LOGIN = '/login';
const HOME = '/';
const ONBOARDING = '/onboarding';
const ABOUT = '/about';
const PRIVACY_POLICY = '/privacy-policy';
const EDU = '/eduaccess';

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
  const needsOnboarding = !!me.data?.user && (!me.data.user.first_name || !me.data.user.last_name);

  // If the page is public, don't redirect to the login page.
  let isPublicPage = false;

  if (url.pathname === LOGIN) {
    // If the user is logged in, go to the home page.
    if (authed) {
      redirect(302, HOME);
    }
  } else {
    if (url.pathname === ABOUT || url.pathname === PRIVACY_POLICY || url.pathname === EDU) {
      isPublicPage = true;
    } else if (!authed) {
      // If the user is not logged in, go to the About page.
      redirect(302, ABOUT);
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
