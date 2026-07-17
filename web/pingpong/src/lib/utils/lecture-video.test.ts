import { describe, expect, it } from 'vitest';

import { getKnowledgeCheckVisualOffsetMs } from './lecture-video';

describe('getKnowledgeCheckVisualOffsetMs', () => {
	it('uses the instant before a visible question boundary', () => {
		expect(getKnowledgeCheckVisualOffsetMs(172_800, 172_800, true)).toBe(172_799);
		expect(getKnowledgeCheckVisualOffsetMs(172_850, 172_800, true)).toBe(172_799);
	});

	it('does not override the visual before the boundary or without a visible question', () => {
		expect(getKnowledgeCheckVisualOffsetMs(172_799, 172_800, true)).toBeNull();
		expect(getKnowledgeCheckVisualOffsetMs(172_800, 172_800, false)).toBeNull();
	});

	it('does not produce a negative offset for a question at the beginning', () => {
		expect(getKnowledgeCheckVisualOffsetMs(0, 0, true)).toBe(0);
	});
});
