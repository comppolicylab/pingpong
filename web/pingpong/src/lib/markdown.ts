import { Marked, type MarkedExtension, type TokensList } from 'marked';
import { markedHighlight } from 'marked-highlight';
import { markedKatex } from './marked-katex';
import hljs from 'highlight.js';
import { memoize } from './memoize';

/**
 * List of available markdown extensions.
 */
const EXTENSIONS: { [key: string]: MarkedExtension } = {
	syntax: markedHighlight({
		langPrefix: 'hljs language-',
		highlight: (code, lang) => {
			const language = hljs.getLanguage(lang) ? lang : 'plaintext';
			return hljs.highlight(code, { language }).value;
		}
	}),
	latex: markedKatex({ throwOnError: false })
};

/**
 * Options to enable or disable markdown extensions.
 *
 * See `EXTENSIONS` for a list of available extensions.
 */
export type MarkdownRendererOptions = Partial<{ [k in keyof typeof EXTENSIONS]: boolean }>;

/**
 * Default renderer options.
 */
const DEFAULT_OPTIONS: MarkdownRendererOptions = {
	latex: false,
	syntax: true
};

const validateMarkdownRendererOptions = (options: MarkdownRendererOptions) => {
	for (const key of Object.keys(options)) {
		if (!(key in EXTENSIONS)) {
			throw new Error(`Unknown markdown extension: ${key}`);
		}
	}
};

/**
 * Get a markdown renderer instance.
 */
const getMarkdownRenderer = (options: MarkdownRendererOptions) => {
	// Build list of enabled extensions
	const extensions: MarkedExtension[] = [];
	if (options.syntax) {
		extensions.push(EXTENSIONS.syntax);
	}
	if (options.latex) {
		extensions.push(EXTENSIONS.latex);
	}

	return new Marked(...extensions);
};

/**
 * Generate a key from the enabled extensions.
 *
 * Example:
 *   { latex: true, syntax: false } => 'latex'
 *   { latex: true, syntax: true } => 'latex,syntax'
 */
const keyFromOpts = (opts: MarkdownRendererOptions) => {
	return Object.entries(opts)
		.filter(([, v]) => v)
		.map(([k]) => k)
		.sort()
		.join(',');
};

/**
 * Memoized version of `getMarkdownRenderer`.
 *
 * Use this to avoid creating a new renderer instance for every markdown string.
 */
const getCachedRenderer = memoize(getMarkdownRenderer, keyFromOpts);

/**
 * Convert markdown to HTML.
 */
export const markdown = (str: string, options?: MarkdownRendererOptions) => {
	const fullOpts = { ...DEFAULT_OPTIONS, ...(options || {}) };
	validateMarkdownRendererOptions(fullOpts);
	const renderer = getCachedRenderer(fullOpts);
	return renderer.parse(str);
};

export const lexMarkdown = (str: string, options?: MarkdownRendererOptions) => {
	const fullOpts = { ...DEFAULT_OPTIONS, ...(options || {}) };
	validateMarkdownRendererOptions(fullOpts);
	const renderer = getCachedRenderer(fullOpts);
	return renderer.lexer(str);
};

export const renderMarkdownTokens = (tokens: TokensList, options?: MarkdownRendererOptions) => {
	const fullOpts = { ...DEFAULT_OPTIONS, ...(options || {}) };
	validateMarkdownRendererOptions(fullOpts);
	const renderer = getCachedRenderer(fullOpts);
	return renderer.parser(tokens);
};
