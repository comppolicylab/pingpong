import type { MarkdownRendererOptions } from './markdown';
import { lexMarkdown, renderMarkdownTokens } from './markdown';
import type { TokensList } from 'marked';

export type MarkdownSegment =
	| { type: 'html'; content: string }
	| { type: 'mermaid-complete'; source: string }
	| { type: 'mermaid-streaming'; source: string }
	| { type: 'svg-complete'; source: string }
	| { type: 'svg-streaming'; source: string }
	| {
			type: 'wrapped-diagram';
			content: string;
			placeholderId: string;
			diagram: DiagramSegment;
	  };

type DiagramSegment =
	| { type: 'mermaid-complete'; source: string }
	| { type: 'mermaid-streaming'; source: string }
	| { type: 'svg-complete'; source: string }
	| { type: 'svg-streaming'; source: string };
type HtmlTokenSegment = { type: 'html-tokens'; tokens: TokensList };
type WrappedDiagramTokenSegment = {
	type: 'wrapped-diagram-tokens';
	tokens: TokensList;
	placeholderId: string;
	diagram: DiagramSegment;
};
type InternalSegment = HtmlTokenSegment | DiagramSegment | WrappedDiagramTokenSegment;
type TokenWithChildren = {
	type?: string;
	tokens?: TokensList;
	items?: Array<TokenWithChildren>;
	lang?: string;
	raw?: string;
	text?: string;
	ordered?: boolean;
	start?: number;
};

const SVG_LANGUAGES = new Set(['svg', 'image/svg+xml']);
const DIAGRAM_FENCE_OPEN_PATTERN = /^[ \t]{0,3}(`{3,})[ \t]*(mermaid|svg|image\/svg\+xml)\b/i;
const FENCE_CLOSE_PATTERN = /^[ \t]{0,3}(`{3,})[ \t]*$/;
let placeholderIdCounter = 0;

const withLinks = (tokens: unknown[], links: TokensList['links']) => {
	const tokenList = tokens as TokensList;
	tokenList.links = links;
	return tokenList;
};

const nextPlaceholderId = () => `markdown-diagram-${placeholderIdCounter++}`;

const createPlaceholderToken = (placeholderId: string) => ({
	type: 'html',
	raw: `<div data-markdown-diagram-placeholder="${placeholderId}"></div>`,
	block: true,
	pre: false,
	text: `<div data-markdown-diagram-placeholder="${placeholderId}"></div>`
});

const createHtmlTokenSegment = (
	tokens: unknown[],
	links: TokensList['links']
): HtmlTokenSegment => {
	return { type: 'html-tokens', tokens: withLinks(tokens, links) };
};

const createWrappedDiagramTokenSegment = (
	tokens: unknown[],
	links: TokensList['links'],
	placeholderId: string,
	diagram: DiagramSegment
): WrappedDiagramTokenSegment => {
	return {
		type: 'wrapped-diagram-tokens',
		tokens: withLinks(tokens, links),
		placeholderId,
		diagram
	};
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
			if (segment.type === 'wrapped-diagram-tokens') {
				return segment;
			}

			const placeholderId = nextPlaceholderId();
			return createWrappedDiagramTokenSegment(
				[
					{
						...token,
						tokens: withLinks([createPlaceholderToken(placeholderId)], links)
					}
				],
				links,
				placeholderId,
				segment
			);
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
	let bufferedItemStartOffset = 0;

	const flushItems = () => {
		if (!bufferedItems.length) {
			return;
		}

		segments.push(
			createHtmlTokenSegment(
				[
					{
						...token,
						items: [...bufferedItems],
						start: token.ordered ? (token.start ?? 1) + bufferedItemStartOffset : token.start
					}
				],
				links
			)
		);
		bufferedItemStartOffset += bufferedItems.length;
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
			if (segment.type === 'wrapped-diagram-tokens') {
				segments.push(
					createWrappedDiagramTokenSegment(
						[
							{
								...token,
								items: [
									{
										...item,
										tokens: withLinks([createPlaceholderToken(segment.placeholderId)], links)
									}
								],
								start: token.ordered ? (token.start ?? 1) + bufferedItemStartOffset : token.start
							}
						],
						links,
						segment.placeholderId,
						segment.diagram
					)
				);
			} else {
				segments.push(segment);
			}
			bufferedItemStartOffset += 1;
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
	placeholderIdCounter = 0;
	const tokens = lexMarkdown(markdownContent, options);
	const segments = splitBlockTokens(tokens)
		.map((segment) => {
			if (segment.type !== 'html-tokens') {
				if (segment.type === 'wrapped-diagram-tokens') {
					return {
						type: 'wrapped-diagram' as const,
						content: renderMarkdownTokens(segment.tokens, options),
						placeholderId: segment.placeholderId,
						diagram: segment.diagram
					};
				}

				return segment;
			}

			return {
				type: 'html' as const,
				content: renderMarkdownTokens(segment.tokens, options)
			};
		})
		.filter((segment) => segment.type !== 'html' || segment.content.length > 0);

	if (!segments.length) {
		return [{ type: 'html', content: renderMarkdownTokens(tokens, options) }];
	}

	return segments;
};
