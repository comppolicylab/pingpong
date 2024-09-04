// A KaTeX-rendering extension for Marked.
// See also https://github.com/UziTech/marked-katex-extension
// which has some limitations and bugs.

import katex, { type KatexOptions } from 'katex';

type KatexToken = {
  type: 'katex';
  raw: string;
  content: string;
  display: boolean;
};

/**
 * Description of a KaTeX delimeter.
 */
export type KatexDelimeter = {
  left: string | RegExp;
  right: string | RegExp;
  display: boolean;
  preserve?: boolean;
};

/**
 * Options for KaTeX rendering.
 */
export type MarkedKatexOptions = KatexOptions & {
  delimeters: KatexDelimeter[];
};

/**
 * Default options for KaTeX rendering.
 */
const DEFAULT_OPTIONS: MarkedKatexOptions = {
  delimeters: [
    { left: '$$', right: '$$', display: true },
    { left: '$', right: '$', display: false },
    { left: '\\(', right: '\\)', display: false },
    { left: '\\[', right: '\\]', display: true },
    { left: /\\begin\{(.*?)\}/, right: /\\end\{\\1\}/, display: true, preserve: true }
  ]
};

/**
 * Escape a string for use in a regular expression.
 */
const escapeRegExp = (str: string) => {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
};

/**
 * Create a KaTeX extension for Marked that renders with the given delimeters.
 */
const markedKatexExtension = (delimeter: KatexDelimeter, options: KatexOptions) => {
  const { left, right, display, preserve } = delimeter;
  const startDelim = left instanceof RegExp ? left : new RegExp(escapeRegExp(left));
  const endDelim = right instanceof RegExp ? right : new RegExp(escapeRegExp(right));
  return {
    name: 'katex',
    // HACK(jnu): the level is *always* `inline` even when we're going to render in block
    // mode in order to force Marked to render "display mode" KaTeX inside of inline elements,
    // such as list items. It doesn't always look great, but it's better than not rendering
    // the KaTeX at all in these cases.
    level: 'inline' as const,
    start(src: string) {
      const x = src.match(startDelim)?.index;
      return x;
    },
    tokenizer(src: string): KatexToken | undefined {
      // Escape the delimeters and create a regular expression.
      const pattern = `^${startDelim.source}([^(?:${endDelim.source})]+)${endDelim.source}`;
      const match = src.match(new RegExp(pattern, 'm'));
      if (match) {
        const [full, content] = match;
        return {
          type: 'katex',
          raw: full,
          // If `preserve` is specified, keep start and end delimiters.
          content: preserve ? full : content,
          display
        };
      }
      return undefined;
    },
    renderer(token: KatexToken) {
      return katex.renderToString(token.content, {
        displayMode: token.display,
        ...options
      });
    }
  };
};

/**
 * KaTeX support for Marked.
 */
export const markedKatex = (options: Partial<MarkedKatexOptions> = {}) => {
  const opts = { ...DEFAULT_OPTIONS, ...options };
  return {
    extensions: opts.delimeters.map((delim) => markedKatexExtension(delim, opts))
  };
};
