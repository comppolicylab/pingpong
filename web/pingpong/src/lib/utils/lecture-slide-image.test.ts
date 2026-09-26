import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLectureSlideImagePreloader } from './lecture-slide-image';

afterEach(() => vi.unstubAllGlobals());

describe('slide image preloading', () => {
	function setup(fail = false) {
		const images: {
			src: string;
			decode: ReturnType<typeof vi.fn>;
			removeAttribute: ReturnType<typeof vi.fn>;
		}[] = [];
		vi.stubGlobal(
			'Image',
			class {
				src = '';
				decode = fail
					? vi.fn().mockRejectedValue(new Error('decode failed'))
					: vi.fn().mockResolvedValue(undefined);
				removeAttribute = vi.fn();
				constructor() {
					images.push(this);
				}
			}
		);
		return images;
	}

	it('deduplicates exact URLs and decodes speculative images', () => {
		const images = setup();
		const preload = createLectureSlideImagePreloader();
		preload('/slide?token=a');
		preload('/slide?token=a');
		preload('/slide?token=b');
		expect(images).toHaveLength(2);
		expect(images.map((image) => image.src)).toEqual(['/slide?token=a', '/slide?token=b']);
		expect(images[0].decode).toHaveBeenCalledOnce();
	});

	it('bounds retained and pending images and evicts least recently requested URLs', () => {
		const images = setup();
		const preload = createLectureSlideImagePreloader(2);
		preload('/a');
		preload('/b');
		preload('/a');
		preload('/c');
		expect(images[0].removeAttribute).not.toHaveBeenCalled();
		expect(images[1].removeAttribute).toHaveBeenCalledWith('src');
	});

	it('does not repeatedly request a failed preload on every timeline update', async () => {
		const images = setup(true);
		const preload = createLectureSlideImagePreloader();
		preload('/bad');
		await Promise.resolve();
		preload('/bad');
		expect(images).toHaveLength(1);
	});
});
