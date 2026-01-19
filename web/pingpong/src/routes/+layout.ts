import { redirect, error } from '@sveltejs/kit';
import * as api from '$lib/api';
import { hasAnonymousSessionToken, setAnonymousShareToken } from '$lib/stores/anonymous';
import type { LayoutLoad } from './$types';
const LOGIN = '/login';
const HOME = '/';
const ONBOARDING = '/onboarding';
const TERMS = '/terms';
const ABOUT = '/about';
const PRIVACY_POLICY = '/privacy-policy';
const EDU = '/eduaccess';
const LOGOUT = '/logout';
const LTI_REGISTER = '/lti/register';
const LTI_INACTIVE = '/lti/inactive';
const LTI_NO_ROLE = '/lti/no-role';
const NO_GROUP = '/lti/no-group';
const SETUP = '/lti/setup';

/**
 * Load the current user and redirect if they are not logged in.
 */
export const load: LayoutLoad = async ({ fetch, url }) => {
	// Check if we have a share token in the URL.
	// If so, we will allow access to the page without authentication.
	const t = url.searchParams.get('share_token');
	if (t) {
		setAnonymousShareToken(t);
	}

	// Check if we have an LTI session token in the URL.
	const ltiSession = url.searchParams.get('lti_session');

	if (url.pathname === LTI_INACTIVE) {
		api.clearLTISessionToken();
	} else if (ltiSession) {
		// Store the LTI session token if present.
		api.setLTISessionToken(ltiSession);
	}

	// Helper to append lti_session to redirect URLs during SSR.
	// This ensures the token is preserved across redirects before client hydration.
	const buildRedirect = (path: string) => {
		if (ltiSession) {
			const separator = path.includes('?') ? '&' : '?';
			return `${path}${separator}lti_session=${encodeURIComponent(ltiSession)}`;
		}
		return path;
	};

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
	const needsAgreements = me.data?.agreement_id !== null;
	let doNotShowSidebar = false;
	let showCollapsedSidebarOnly = false;
	let openAllLinksInNewTab = false;
	let logoIsClickable = true;
	let showSidebarItems = true;

	// If the page is public, don't redirect to the login page.
	let isPublicPage = false;

	// Check if the url has format /group/[classId]/shared/assistant/[assistantId]
	const sharedAssistantPattern = /\/group\/(\d+)\/shared\/assistant\/(\d+)/;
	const sharedThreadPattern = /\/group\/(\d+)\/shared\/thread\/(\d+)/;
	const isSharedAssistantPage = sharedAssistantPattern.test(url.pathname);
	const isSharedThreadPage = sharedThreadPattern.test(url.pathname);

	if (url.pathname === LOGIN) {
		// If the user is logged in, go to the forward page.
		if (authed) {
			const destination = url.searchParams.get('forward') || HOME;
			redirect(302, destination);
		}
	} else {
		if (
			url.pathname === LTI_REGISTER ||
			url.pathname === LTI_INACTIVE ||
			url.pathname === LTI_NO_ROLE
		) {
			isPublicPage = true;
			openAllLinksInNewTab = true;
			logoIsClickable = false;
			if (url.pathname === LTI_REGISTER) {
				showCollapsedSidebarOnly = true;
				showSidebarItems = false;
			}
		} else if (url.pathname === NO_GROUP || url.pathname.startsWith(SETUP)) {
			doNotShowSidebar = true;
			logoIsClickable = false;
		} else if (new Set([ABOUT, PRIVACY_POLICY, EDU, HOME]).has(url.pathname) && !authed) {
			isPublicPage = true;
			if (url.pathname === HOME) {
				// If the user is not logged in and tries to access the root path, go to the About page.
				redirect(302, ABOUT);
			}
		} else if (
			!authed &&
			((t && isSharedAssistantPage) || (hasAnonymousSessionToken() && isSharedThreadPage))
		) {
			// If the user is not logged in and the URL has a share token,
			// allow access to the shared assistant or thread page.
			// doNotShowSidebar = true;
		} else if (!authed && url.pathname !== LOGOUT) {
			const destination = encodeURIComponent(`${url.pathname}${url.search}`);
			redirect(302, buildRedirect(`${LOGIN}?forward=${destination}`));
		} else {
			if ((needsAgreements && url.pathname === TERMS) || url.pathname === LOGOUT) {
				// If the user is logged in and tries to access the logout or terms page, don't show the sidebar.
				doNotShowSidebar = true;
			} else if (needsAgreements && url.pathname !== TERMS && url.pathname !== PRIVACY_POLICY) {
				// If the user is logged in and hasn't agreed to the terms, redirect them to the terms page. Exclude the privacy policy page.
				doNotShowSidebar = true;
				const destination = encodeURIComponent(`${url.pathname}${url.search}`);
				redirect(302, buildRedirect(`${TERMS}?forward=${destination}&id=${me.data.agreement_id}`));
			} else if (!needsAgreements && url.pathname === TERMS) {
				// Just in case someone tries to go to the terms page when they don't need to.
				const destination = url.searchParams.get('forward') || HOME;
				redirect(302, destination);
			} else if (needsOnboarding && url.pathname !== ONBOARDING) {
				const destination = encodeURIComponent(`${url.pathname}${url.search}`);
				redirect(302, buildRedirect(`${ONBOARDING}?forward=${destination}`));
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
	let isRootAdmin = false;
	let modelInfo: api.AssistantModelLite[] = [];
	let grantResults;
	if (authed) {
		[classes, threads, grantResults, institutions, modelInfo] = await Promise.all([
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
					},
					isRootAdmin: {
						target_type: 'root',
						target_id: 0,
						relation: 'admin'
					}
				})
				.then((g) => g),
			api
				.getInstitutions(fetch, 'can_create_class')
				.then(api.explodeResponse)
				.then((i) => i.institutions),
			api
				.getModelsLite(fetch)
				.then(api.explodeResponse)
				.then((m) => m.models)
		]);
		canCreateInstitution = grantResults.canCreateInstitution;
		isRootAdmin = grantResults.isRootAdmin;
	}

	const admin = {
		canCreateInstitution,
		canCreateClass: institutions,
		isRootAdmin,
		showAdminPage: authed && (canCreateInstitution || institutions.length > 0)
	};

	let hasNonComponentIncidents = false;

	const componentIncidents: Record<string, Record<string, api.StatusComponentUpdate>> = {};

	try {
		const statusResponse = await fetch(
			'https://q559jtpt3rsz.statuspage.io/api/v2/incidents/unresolved.json'
		);
		if (statusResponse.ok) {
			const statusJson = (await statusResponse.json()) as {
				incidents?: Array<{
					id: string;
					name: string;
					status: string;
					updated_at?: string | null;
					shortlink?: string | null;
					impact?: string | null;
					incident_updates?: Array<{
						id: string;
						status: string;
						body: string;
						created_at?: string | null;
						updated_at?: string | null;
						display_at?: string | null;
						affected_components?: Array<{
							code: string;
						}>;
					}>;
					components?: Array<{
						group_id: string | null;
					}>;
				}>;
			};

			for (const incident of statusJson.incidents ?? []) {
				let affectedAny = false;
				let hasPingPongWebGroupComponent = false;
				for (const component of incident.components ?? []) {
					if (!component.group_id || component.group_id !== api.STATUS_COMPONENT_GROUP_ID) {
						continue;
					}
					hasPingPongWebGroupComponent = true;
				}

				for (const update of incident.incident_updates ?? []) {
					const affected = update.affected_components ?? [];
					const timestampSource =
						update.display_at ??
						update.updated_at ??
						update.created_at ??
						incident.updated_at ??
						null;
					const timestamp = timestampSource ? Date.parse(timestampSource) : Number.NaN;

					for (const component of affected) {
						if (!Object.values(api.STATUS_COMPONENT_IDS).includes(component.code)) {
							continue;
						}
						affectedAny = true;

						if (!componentIncidents[component.code]) {
							componentIncidents[component.code] = {};
						}

						const existing = componentIncidents[component.code][incident.id];
						const existingTimestamp = existing?.updatedAt
							? Date.parse(existing.updatedAt)
							: Number.NaN;
						const hasTimestamp = !Number.isNaN(timestamp);
						const shouldReplace =
							!existing ||
							(hasTimestamp && (Number.isNaN(existingTimestamp) || existingTimestamp < timestamp));

						if (!shouldReplace) {
							continue;
						}

						componentIncidents[component.code][incident.id] = {
							incidentId: incident.id,
							incidentName: incident.name,
							incidentStatus: incident.status,
							updateStatus: update.status,
							body: update.body,
							updatedAt: timestampSource,
							shortlink: incident.shortlink ?? null,
							impact: incident.impact ?? null
						};
					}
				}
				if (!affectedAny && hasPingPongWebGroupComponent) {
					hasNonComponentIncidents = true;
				}
			}
		}
	} catch (err) {
		console.error('Failed to load status page incidents', err);
	}

	const statusComponents: Record<string, api.StatusComponentUpdate[]> = {};
	for (const [componentCode, incidents] of Object.entries(componentIncidents)) {
		statusComponents[componentCode] = Object.values(incidents).sort((a, b) => {
			const timeA = a.updatedAt ? Date.parse(a.updatedAt) : 0;
			const timeB = b.updatedAt ? Date.parse(b.updatedAt) : 0;
			return timeB - timeA;
		});
	}

	return {
		isPublicPage,
		needsOnboarding,
		needsAgreements,
		doNotShowSidebar,
		showCollapsedSidebarOnly,
		openAllLinksInNewTab,
		logoIsClickable,
		showSidebarItems,
		me: me.data,
		authed,
		classes,
		threads,
		admin,
		modelInfo,
		shareToken: t,
		isSharedAssistantPage,
		isSharedThreadPage,
		statusComponents,
		hasNonComponentIncidents
	};
};
