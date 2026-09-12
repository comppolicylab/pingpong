import { describe, expect, it } from 'vitest';

import { lecturePronunciationError } from './lecturePronunciation';

describe('lecture pronunciation annotations', () => {
	it('accepts ASCII annotations in ordinary narration', () => {
		expect(lecturePronunciationError('The pipes [[lead=>leed]] water away.')).toBeNull();
		expect(
			lecturePronunciationError('Old [[lead=>led]] pipes [[lead=>leed]] water away.')
		).toBeNull();
		expect(lecturePronunciationError('Use [[ SQL => ess cue ell ]] here.')).toBeNull();
		expect(lecturePronunciationError('Visit [[New York => noo york]] today.')).toBeNull();
		expect(lecturePronunciationError('Use [[data base => database]] here.')).toBeNull();
	});

	it.each([
		'Broken [[lead=leed]].',
		'Broken [[lead=>leed].',
		'Broken [lead=>leed]].',
		'Broken [[ =>spoken]].',
		'Broken [[lead=> ]].',
		'Broken [[lead=>leed=>led]].'
	])('rejects malformed annotation %s', (text) => {
		expect(lecturePronunciationError(text)?.toLowerCase()).toContain('pronunciation');
	});
});
