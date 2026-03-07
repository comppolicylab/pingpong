import type { MarkdownRendererOptions } from './markdown';
import { lexMarkdown, renderMarkdownTokens } from './markdown';
import type { TokensList } from 'marked';

export type MarkdownSegment =
	| { type: 'html'; content: string }
	| { type: 'mermaid-complete'; source: string }
	| { type: 'mermaid-streaming'; source: string }
	| { type: 'svg-complete'; source: string }
	| { type: 'svg-streaming'; source: string };

type DiagramSegment =
	| { type: 'mermaid-complete'; source: string }
	| { type: 'mermaid-streaming'; source: string }
	| { type: 'svg-complete'; source: string }
	| { type: 'svg-streaming'; source: string };
type HtmlTokenSegment = { type: 'html-tokens'; tokens: TokensList };
type InternalSegment = HtmlTokenSegment | DiagramSegment;
type TokenWithChildren = {
	type?: string;
	tokens?: TokensList;
	items?: Array<TokenWithChildren>;
	lang?: string;
	raw?: string;
	text?: string;
};

const SVG_LANGUAGES = new Set(['svg', 'image/svg+xml']);
const DIAGRAM_FENCE_OPEN_PATTERN = /^[ \t]{0,3}(`{3,})[ \t]*(mermaid|svg|image\/svg\+xml)\b/i;
const FENCE_CLOSE_PATTERN = /^[ \t]{0,3}(`{3,})[ \t]*$/;

const withLinks = (tokens: unknown[], links: TokensList['links']) => {
	const tokenList = tokens as TokensList;
	tokenList.links = links;
	return tokenList;
};

const createHtmlTokenSegment = (
	tokens: unknown[],
	links: TokensList['links']
): HtmlTokenSegment => {
	return { type: 'html-tokens', tokens: withLinks(tokens, links) };
};

const normalizeLanguage = (lang: string | undefined) => lang?.trim().toLowerCase() ?? '';

const isClosedDiagramFence = (raw: string | undefined) => {
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

const toDiagramSegment = (token: TokenWithChildren): DiagramSegment | null => {
	const language = normalizeLanguage(token.lang);
	if (language === 'mermaid') {
		return {
			type: isClosedDiagramFence(token.raw) ? 'mermaid-complete' : 'mermaid-streaming',
			source: token.text?.trimEnd() ?? ''
		};
	}

	if (SVG_LANGUAGES.has(language)) {
		return {
			type: isClosedDiagramFence(token.raw) ? 'svg-complete' : 'svg-streaming',
			source: token.text?.trimEnd() ?? ''
		};
	}

	return null;
};

const wrapChildSegments = (
	token: TokenWithChildren,
	childSegments: InternalSegment[],
	links: TokensList['links']
) => {
	return childSegments.map((segment) => {
		if (segment.type !== 'html-tokens') {
			return segment;
		}

		return createHtmlTokenSegment([{ ...token, tokens: segment.tokens }], links);
	});
};

const splitListToken = (
	token: TokenWithChildren,
	links: TokensList['links']
): InternalSegment[] => {
	const segments: InternalSegment[] = [];
	const bufferedItems: TokenWithChildren[] = [];

	const flushItems = () => {
		if (!bufferedItems.length) {
			return;
		}

		segments.push(createHtmlTokenSegment([{ ...token, items: [...bufferedItems] }], links));
		bufferedItems.length = 0;
	};

	for (const item of token.items ?? []) {
		const itemSegments = wrapChildSegments(
			item,
			splitBlockTokens(withLinks([...(item.tokens ?? [])], links)),
			links
		);

		for (const segment of itemSegments) {
			if (segment.type === 'html-tokens') {
				bufferedItems.push(...(segment.tokens as TokenWithChildren[]));
				continue;
			}

			flushItems();
			segments.push(segment);
		}
	}

	flushItems();
	return segments;
};

const splitNestedToken = (token: TokenWithChildren, links: TokensList['links']) => {
	if (token.type === 'blockquote' && token.tokens) {
		return wrapChildSegments(token, splitBlockTokens(withLinks([...token.tokens], links)), links);
	}

	if (token.type === 'list' && token.items) {
		return splitListToken(token, links);
	}

	return null;
};

const splitBlockTokens = (tokens: TokensList): InternalSegment[] => {
	const segments: InternalSegment[] = [];
	const htmlTokens: TokenWithChildren[] = [];

	const flushHtmlTokens = () => {
		if (!htmlTokens.length) {
			return;
		}

		segments.push(createHtmlTokenSegment([...htmlTokens], tokens.links));
		htmlTokens.length = 0;
	};

	for (const token of tokens as TokenWithChildren[]) {
		const diagramSegment = token.type === 'code' ? toDiagramSegment(token) : null;
		if (diagramSegment) {
			flushHtmlTokens();
			segments.push(diagramSegment);
			continue;
		}

		const nestedSegments = splitNestedToken(token, tokens.links);
		if (!nestedSegments) {
			htmlTokens.push(token);
			continue;
		}

		for (const segment of nestedSegments) {
			if (segment.type === 'html-tokens') {
				htmlTokens.push(...(segment.tokens as TokenWithChildren[]));
				continue;
			}

			flushHtmlTokens();
			segments.push(segment);
		}
	}

	flushHtmlTokens();
	return segments;
};

export const parseMarkdownSegments = (
	markdownContent: string,
	options: MarkdownRendererOptions
): MarkdownSegment[] => {
	const tokens = lexMarkdown(markdownContent, options);
	const segments = splitBlockTokens(tokens).map((segment) => {
		if (segment.type !== 'html-tokens') {
			return segment;
		}

		return {
			type: 'html' as const,
			content: renderMarkdownTokens(segment.tokens, options)
		};
	});

	if (!segments.length) {
		return [{ type: 'html', content: renderMarkdownTokens(tokens, options) }];
	}

	return segments;
};
