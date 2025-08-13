import { GET, type Fetcher } from '../utils';
import type { Courses } from '../types';

export const getMyCourses = async (f: Fetcher) => {
	return await GET<never, Courses>(f, 'courses');
};
