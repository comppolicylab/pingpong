import type { PageLoad } from './$types';
import { redirect } from '@sveltejs/kit';

export const load: PageLoad = async ({ parent, url }) => {
	// Generally we just want to redirect users to the class page.
	// We can redirect to the most recent class, or the first class they have access to.
	// If they have no classes, we'll just stay on this page and display a no-data state.
	// TODO - for admins, we should land on this page and show controls.
	const parentData = await parent();
	// Check for an error code in the URL and pass it along to the redirect.
	// We currently only use this when the Canvas token returned from OAuth2 is invalid.
	const errorCode = url.searchParams.get('error_code');
	const userThreads = parentData.threads.filter((thread) => thread.anonymous_session !== true);
	if (userThreads.length > 0) {
		const latestThread = userThreads[0];
		const classId = latestThread.class_id;
		const asstId = latestThread.assistant_id;
		return redirect(
			302,
			`/group/${classId}?assistant=${asstId}${errorCode ? `&error_code=${errorCode}` : ''}`
		);
	} else if (parentData.classes.length > 0) {
		return redirect(
			302,
			`/group/${parentData.classes[0].id}${errorCode ? `?error_code=${errorCode}` : ''}`
		);
	} else if (parentData.admin.showAdminPage) {
		// If we get here, the app is not configured yet (i.e., a new installation).
		// Since the user is an admin, we can redirect them to a page where they can
		// set up their first class.
		return redirect(302, '/admin');
	} else {
		return redirect(302, '/about');
	}

	// If we get here it means the user has no visible items and is
	// also not an admin. The page should just render a no-data state,
	// with an explanation of why they're not seeing anything.
	return {};
};
