import type { TokensList } from 'marked';
import type { Diagram } from './diagram';
import { parseDiagramFence } from './diagram';
import type { MarkdownRendererOptions } from './markdown';
import { lexMarkdown, renderMarkdownTokens } from './markdown';

export type MarkdownSegmentOptions = MarkdownRendererOptions & {
	mermaid?: boolean;
	svg?: boolean;
};

export type MarkdownSegment =
	| { type: 'html'; content: string }
	| { type: 'diagram'; diagram: Diagram }
	| {
			type: 'diagram';
			diagram: Diagram;
			wrapperHtml: string;
			placeholderId: string;
	  };

type HtmlTokenSegment = { type: 'html'; tokens: TokensList };
type DiagramTokenSegment =
	| { type: 'diagram'; diagram: Diagram }
	| { type: 'diagram'; diagram: Diagram; tokens: TokensList; placeholderId: string };
type InternalSegment = HtmlTokenSegment | DiagramTokenSegment;
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

const withLinks = (tokens: unknown[], links: TokensList['links']) => {
	const tokenList = tokens as TokensList;
	tokenList.links = links;
	return tokenList;
};

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
	return { type: 'html', tokens: withLinks(tokens, links) };
};

const createWrappedDiagramTokenSegment = (
	tokens: unknown[],
	links: TokensList['links'],
	placeholderId: string,
	diagram: Diagram
): Extract<DiagramTokenSegment, { tokens: TokensList }> => {
	return {
		type: 'diagram',
		diagram,
		tokens: withLinks(tokens, links),
		placeholderId
	};
};

const isWrappedDiagramTokenSegment = (
	segment: DiagramTokenSegment
): segment is Extract<DiagramTokenSegment, { tokens: TokensList }> => {
	return 'tokens' in segment;
};

const wrapChildSegments = (
	token: TokenWithChildren,
	childSegments: InternalSegment[],
	links: TokensList['links'],
	nextPlaceholderId: () => string
) => {
	return childSegments.map((segment) => {
		if (segment.type === 'html') {
			return createHtmlTokenSegment([{ ...token, tokens: segment.tokens }], links);
		}

		const placeholderId = isWrappedDiagramTokenSegment(segment)
			? segment.placeholderId
			: nextPlaceholderId();
		const childTokens = isWrappedDiagramTokenSegment(segment)
			? segment.tokens
			: withLinks([createPlaceholderToken(placeholderId)], links);

		return createWrappedDiagramTokenSegment(
			[{ ...token, tokens: childTokens }],
			links,
			placeholderId,
			segment.diagram
		);
	});
};

const splitListToken = (
	token: TokenWithChildren,
	links: TokensList['links'],
	nextPlaceholderId: () => string,
	options: MarkdownSegmentOptions
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
			splitBlockTokens(withLinks([...(item.tokens ?? [])], links), nextPlaceholderId, options),
			links,
			nextPlaceholderId
		);

		for (const segment of itemSegments) {
			if (segment.type === 'html') {
				bufferedItems.push(...(segment.tokens as unknown as TokenWithChildren[]));
				continue;
			}

			flushItems();

			if (!isWrappedDiagramTokenSegment(segment)) {
				continue;
			}

			segments.push(
				createWrappedDiagramTokenSegment(
					[
						{
							...token,
							items: [...(segment.tokens as unknown as TokenWithChildren[])],
							start: token.ordered ? (token.start ?? 1) + bufferedItemStartOffset : token.start
						}
					],
					links,
					segment.placeholderId,
					segment.diagram
				)
			);
			bufferedItemStartOffset += 1;
		}
	}

	flushItems();
	return segments;
};

const splitNestedToken = (
	token: TokenWithChildren,
	links: TokensList['links'],
	nextPlaceholderId: () => string,
	options: MarkdownSegmentOptions
) => {
	if (token.type === 'blockquote' && token.tokens) {
		return wrapChildSegments(
			token,
			splitBlockTokens(withLinks([...token.tokens], links), nextPlaceholderId, options),
			links,
			nextPlaceholderId
		);
	}

	if (token.type === 'list' && token.items) {
		return splitListToken(token, links, nextPlaceholderId, options);
	}

	return null;
};

const splitBlockTokens = (
	tokens: TokensList,
	nextPlaceholderId: () => string,
	options: MarkdownSegmentOptions
): InternalSegment[] => {
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
		let diagram =
			token.type === 'code' ? parseDiagramFence(token.lang, token.raw, token.text) : null;
		if (
			diagram &&
			((diagram.kind === 'mermaid' && options.mermaid === false) ||
				(diagram.kind === 'svg' && options.svg === false))
		) {
			diagram = null;
		}
		if (diagram) {
			flushHtmlTokens();
			segments.push({ type: 'diagram', diagram });
			continue;
		}

		const nestedSegments = splitNestedToken(token, tokens.links, nextPlaceholderId, options);
		if (!nestedSegments) {
			htmlTokens.push(token);
			continue;
		}

		for (const segment of nestedSegments) {
			if (segment.type === 'html') {
				htmlTokens.push(...(segment.tokens as unknown as TokenWithChildren[]));
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
	options: MarkdownSegmentOptions
): MarkdownSegment[] => {
	const rendererOptions: MarkdownRendererOptions = {
		syntax: options.syntax,
		latex: options.latex
	};
	let placeholderIdCounter = 0;
	const nextPlaceholderId = () => `markdown-diagram-${placeholderIdCounter++}`;
	const tokens = lexMarkdown(markdownContent, rendererOptions);
	const segments = splitBlockTokens(tokens, nextPlaceholderId, options)
		.map((segment): MarkdownSegment => {
			if (segment.type === 'html') {
				return {
					type: 'html',
					content: renderMarkdownTokens(segment.tokens, rendererOptions)
				};
			}

			if (isWrappedDiagramTokenSegment(segment)) {
				return {
					type: 'diagram',
					diagram: segment.diagram,
					wrapperHtml: renderMarkdownTokens(segment.tokens, rendererOptions),
					placeholderId: segment.placeholderId
				};
			}

			return segment;
		})
		.filter((segment) => segment.type !== 'html' || segment.content.length > 0);

	if (!segments.length) {
		return [{ type: 'html', content: renderMarkdownTokens(tokens, rendererOptions) }];
	}

	return segments;
};
