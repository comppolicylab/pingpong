const SVG_FENCE_OPEN_PATTERN = /^([ \t]{0,3})(`{3,})(?:svg|image\/svg\+xml)\b.*$/i;
const SVG_FENCE_CLOSE_PATTERN = /^([ \t]{0,3})(`{3,})[ \t]*$/;

export const SVG_DOCUMENT_PATTERN = /^(?:<\?xml[\s\S]*?\?>\s*)?<svg\b[\s\S]*<\/svg>$/i;

export const getSvgFenceClosureStates = (markdownSource: string) => {
	const normalizedSource = markdownSource.replace(/\r\n?/g, '\n');
	const lines = normalizedSource.split('\n');
	const fenceStates: boolean[] = [];

	let openFence:
		| {
				indent: string;
				fenceLength: number;
		  }
		| undefined;

	for (const line of lines) {
		if (!openFence) {
			const openMatch = line.match(SVG_FENCE_OPEN_PATTERN);
			if (!openMatch) {
				continue;
			}

			openFence = {
				indent: openMatch[1],
				fenceLength: openMatch[2].length
			};
			continue;
		}

		const closeMatch = line.match(SVG_FENCE_CLOSE_PATTERN);
		if (
			closeMatch &&
			closeMatch[1] === openFence.indent &&
			closeMatch[2].length >= openFence.fenceLength
		) {
			fenceStates.push(true);
			openFence = undefined;
		}
	}

	if (openFence) {
		fenceStates.push(false);
	}

	return fenceStates;
};
