export const LECTURE_PRONUNCIATION_EXAMPLE = '[[lead=>leed]]';

const pronunciationPattern = /\[\[([^\s[\]]+)=>([^\s[\]]+)\]\]/g;

export const lecturePronunciationError = (text: string): string | null => {
	if (!text.includes('[[') && !text.includes(']]')) return null;

	let cursor = 0;
	let found = false;
	for (const match of text.matchAll(pronunciationPattern)) {
		const index = match.index ?? 0;
		const between = text.slice(cursor, index);
		if (between.includes('[[') || between.includes(']]')) {
			return `Malformed pronunciation. Use ${LECTURE_PRONUNCIATION_EXAMPLE}.`;
		}
		const [, written, spoken] = match;
		if (written.includes('=>') || spoken.includes('=>')) {
			return 'Pronunciation annotations must contain exactly one => separator.';
		}
		found = true;
		cursor = index + match[0].length;
	}

	const remainder = text.slice(cursor);
	if (!found || remainder.includes('[[') || remainder.includes(']]')) {
		return `Malformed pronunciation. Use ${LECTURE_PRONUNCIATION_EXAMPLE}.`;
	}
	return null;
};
