import { writable, derived, get } from 'svelte/store';
import type { Course } from '$lib/api/types';
import { getMyCourses } from '$lib/api/client';
import { explodeResponse } from '$lib/api/utils';
import type { Fetcher } from '$lib/api/utils/types';

// State stores
export const courses = writable<Course[]>([]);
// Default to true so SSR shows skeletons until client fetch kicks in
export const loading = writable<boolean>(true);
export const loaded = writable<boolean>(false);
export const error = writable<string | null>(null);

let inflight: Promise<Course[]> | null = null;

/**
 * Ensure courses are loaded. Deduplicates concurrent calls and caches result.
 */
export const ensureCourses = async (fetch: Fetcher) => {
	if (get(loaded)) return get(courses);
	if (inflight) return inflight;

	loading.set(true);
	error.set(null);

	inflight = getMyCourses(fetch)
		.then(explodeResponse)
		.then((res) => {
			const list = res.courses ?? [];
			courses.set(list);
			loaded.set(true);
			return list as Course[];
		})
		.catch((e) => {
			error.set(typeof e === 'string' ? e : (e?.detail ?? 'Failed to load courses'));
			throw e;
		})
		.finally(() => {
			loading.set(false);
			inflight = null;
		});

	return inflight;
};

/**
 * Get a course by id from the store (snapshot).
 */
export const getCourseById = (id: string) => get(courses).find((c) => c.id === id);

/**
 * Reactive helper: returns a derived store for a course by id.
 * Usage in Svelte: `const course = courseById(id);` then `$course?.name`
 */
export const courseById = (id: string) =>
	derived(courses, ($courses) => $courses.find((c) => c.id === id));
