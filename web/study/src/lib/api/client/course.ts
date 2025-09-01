import { GET, PATCH, type Fetcher } from '../utils';
import type { Courses } from '../types';

export const getMyCourses = async (f: Fetcher) => {
	return await GET<never, Courses>(f, 'courses');
};

export const updateCourseEnrollment = async (
	f: Fetcher,
	courseId: string,
	enrollment_count: number
) => {
	return await PATCH<{ enrollment_count: number }, { status: string }>(
		f,
		`courses/${courseId}/enrollment`,
		{ enrollment_count }
	);
};
