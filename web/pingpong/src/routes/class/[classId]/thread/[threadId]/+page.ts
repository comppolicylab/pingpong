import type { PageLoad } from './$types';
import { redirect } from '@sveltejs/kit';

export const load: PageLoad = async ({ params }) => {
	const classId = parseInt(params.classId, 10);
	const threadId = parseInt(params.threadId, 10);
	redirect(302, `/group/${classId}/thread/${threadId}/`);
};
