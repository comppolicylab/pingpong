import { describe, expect, it } from 'vitest';
import { lectureChatBreakOffset } from './lecture-chat-break';

describe('lectureChatBreakOffset', () => {
	it('waits across partial captions until the sentence ends', () => {
		expect(
			lectureChatBreakOffset(500, [
				{ startTime: 0, endTime: 2, text: 'This is' },
				{ startTime: 2, endTime: 4, text: 'one sentence.' },
				{ startTime: 4, endTime: 6, text: 'Next sentence.' }
			])
		).toBe(4000);
	});
	it('recognizes a gap in speech without punctuation', () => {
		expect(
			lectureChatBreakOffset(500, [
				{ startTime: 0, endTime: 2, text: 'a phrase' },
				{ startTime: 3, endTime: 5, text: 'another phrase' }
			])
		).toBe(2000);
	});
	it('pauses immediately when already in a caption gap or timing is unavailable', () => {
		expect(
			lectureChatBreakOffset(2500, [
				{ startTime: 0, endTime: 2, text: 'Done.' },
				{ startTime: 3, endTime: 5, text: 'Next.' }
			])
		).toBeNull();
		expect(lectureChatBreakOffset(500, [])).toBeNull();
	});
	it('uses the next slide narration segment end', () => {
		expect(lectureChatBreakOffset(2500, [], [2000, 4000, 6000])).toBe(4000);
	});
	it('bounds the wait for poorly punctuated captions', () => {
		expect(
			lectureChatBreakOffset(500, [
				{ startTime: 0, endTime: 2, text: 'A long' },
				{ startTime: 2, endTime: 20, text: 'unpunctuated sentence' }
			])
		).toBe(2000);
	});
});
