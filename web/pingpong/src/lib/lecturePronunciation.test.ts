import { describe, expect, it } from 'vitest';

import { lecturePronunciationError } from './lecturePronunciation';

describe('lecture pronunciation annotations', () => {
	it('accepts ASCII annotations in ordinary narration', () => {
		expect(lecturePronunciationError('The pipes [[lead=>leed]] water away.')).toBeNull();
		expect(
			lecturePronunciationError('Old [[lead=>led]] pipes [[lead=>leed]] water away.')
		).toBeNull();
	});

	it.each([
		'Broken [[lead=leed]].',
		'Broken [[lead=>leed].',
		'Broken [lead=>leed]].',
		'Broken [[two words=>spoken]].',
		'Broken [[lead=>two words]].',
		'Broken [[lead=>leed=>led]].'
	])('rejects malformed annotation %s', (text) => {
		expect(lecturePronunciationError(text)?.toLowerCase()).toContain('pronunciation');
	});
});
