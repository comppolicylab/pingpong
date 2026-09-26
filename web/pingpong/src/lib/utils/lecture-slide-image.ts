// Keep decoded images alive near the playhead without retaining an entire deck.
// Exact URLs include any authentication/version query parameters.
export function createLectureSlideImagePreloader(limit = 4) {
	const entries = new Map<string, HTMLImageElement>();
	return (src: string) => {
		if (typeof Image === 'undefined') return;
		const existing = entries.get(src);
		if (existing) {
			entries.delete(src);
			entries.set(src, existing);
			return;
		}
		const image = new Image();
		entries.set(src, image);
		image.src = src;
		// Keep failed entries until eviction so timeline updates do not retry in a loop.
		void image.decode().catch(() => {});
		while (entries.size > limit) {
			const oldest = entries.keys().next().value!;
			const evicted = entries.get(oldest)!;
			entries.delete(oldest);
			// These elements are only speculative loads, never mounted slide images.
			evicted.removeAttribute('src');
		}
	};
}

export const preloadLectureSlideImage = createLectureSlideImagePreloader();
