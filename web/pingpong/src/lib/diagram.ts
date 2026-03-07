export type DiagramKind = 'mermaid' | 'svg';
export type DiagramState = 'complete' | 'streaming';
export type Diagram = {
	kind: DiagramKind;
	state: DiagramState;
	source: string;
};

const DIAGRAM_FENCE_KINDS: Record<string, DiagramKind> = {
	mermaid: 'mermaid',
	svg: 'svg',
	'image/svg+xml': 'svg'
};

const DIAGRAM_FENCE_OPEN_PATTERN = /^[ \t]{0,3}(`{3,})[ \t]*(mermaid|svg|image\/svg\+xml)\b/i;
const FENCE_CLOSE_PATTERN = /^[ \t]{0,3}(`{3,})[ \t]*$/;

export const SVG_DOCUMENT_PATTERN = /^\s*(?:<\?xml[\s\S]*?\?>\s*)?<svg\b[\s\S]*<\/svg>\s*$/i;

export const getDiagramLabel = (kind: DiagramKind) => (kind === 'svg' ? 'SVG' : 'Mermaid');

const normalizeFenceLanguage = (language: string | undefined) =>
	language?.trim().toLowerCase() ?? '';

export const getDiagramKind = (language: string | undefined): DiagramKind | null => {
	return DIAGRAM_FENCE_KINDS[normalizeFenceLanguage(language)] ?? null;
};

export const isClosedDiagramFence = (raw: string | undefined) => {
	if (!raw) {
		return false;
	}

	const lines = raw.replace(/\r\n?/g, '\n').split('\n');
	while (lines.length > 1 && lines[lines.length - 1] === '') {
		lines.pop();
	}

	const openMatch = lines[0]?.match(DIAGRAM_FENCE_OPEN_PATTERN);
	const closeMatch = lines[lines.length - 1]?.match(FENCE_CLOSE_PATTERN);
	return !!openMatch && !!closeMatch && closeMatch[1].length >= openMatch[1].length;
};

export const parseDiagramFence = (
	language: string | undefined,
	raw: string | undefined,
	source: string | undefined
): Diagram | null => {
	const kind = getDiagramKind(language);
	if (!kind) {
		return null;
	}

	return {
		kind,
		state: isClosedDiagramFence(raw) ? 'complete' : 'streaming',
		source: source?.trimEnd() ?? ''
	};
};

let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;

export const getMermaid = async () => {
	if (!mermaidPromise) {
		mermaidPromise = import('mermaid')
			.then(({ default: mermaid }) => {
				mermaid.initialize({
					startOnLoad: false,
					theme: 'neutral',
					securityLevel: 'strict'
				});
				return mermaid;
			})
			.catch((error) => {
				mermaidPromise = null;
				throw error;
			});
	}

	return mermaidPromise;
};
