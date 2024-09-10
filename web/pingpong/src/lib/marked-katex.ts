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
 * Description of a KaTeX delimiter.
 */
export type KatexDelimiter = {
  left: string | RegExp;
  /**
   * The right delimiter can be a string literal, a regular expression,
   * or a function that generates a regular expression based on the left
   * delimiter (expressed as a regular expression match result, in case
   * a capturing group needs to be referenced).
   */
  right: string | RegExp | ((match: RegExpMatchArray) => RegExp);
  display: boolean;
  preserve?: boolean;
};

/**
 * Options for KaTeX rendering.
 */
export type MarkedKatexOptions = KatexOptions & {
  delimiters: KatexDelimiter[];
};

/**
 * Default options for KaTeX rendering.
 */
const DEFAULT_OPTIONS: MarkedKatexOptions = {
  delimiters: [
    { left: '$$', right: '$$', display: true },
    { left: '$', right: '$', display: false },
    { left: '\\(', right: '\\)', display: false },
    { left: '\\[', right: '\\]', display: true },
    { left: /\\begin\{(.*?)\}/, right: m => new RegExp(`\\\\end\\{${escapeRegExp(m[1])}\\}`), display: true, preserve: true }
  ]
};

/**
 * Escape a string for use in a regular expression.
 */
const escapeRegExp = (str: string) => {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
};

/**
 * Create a KaTeX extension for Marked that renders with the given delimiters.
 */
const markedKatexExtension = (delimiters: MarkedKatexOptions["delimiters"], options: KatexOptions) => {
  const delims = delimiters.map((delimiter) => {
    const { left, right, display, preserve } = delimiter;
    const startDelim = left instanceof RegExp ? left : new RegExp(escapeRegExp(left));
    const beginsWithStartDelim = new RegExp(`^${startDelim.source}`);
    return { startDelim, right, display, preserve, beginsWithStartDelim };
  });
  return {
    name: 'katex',
    // HACK(jnu): the level is *always* `inline` even when we're going to render in block
    // mode in order to force Marked to render "display mode" KaTeX inside of inline elements,
    // such as list items. It doesn't always look great, but it's better than not rendering
    // the KaTeX at all in these cases.
    level: 'inline' as const,
    start(src: string) {
      // Find the first occurrence of any possible delimiter in the string.
      // The string might contain multiple delimiters, or none.
      let earliestMatch = Infinity;
      for (const { startDelim } of delims) {
        const match = src.match(startDelim);
        if (match && match.index !== undefined) {
          earliestMatch = Math.min(earliestMatch, match.index);
        }
      }

      return isFinite(earliestMatch) ? earliestMatch : undefined;
    },
    tokenizer(src: string): KatexToken | undefined {
      let delim: typeof delims[number] | undefined;
      let startMatch: RegExpMatchArray | null = null;
      let longestMatchLength = 0;

      // Search for the best (longest) delimiter to use. This avoids
      // issues where a shorter delimiter is found first, such as when
      // both `$` and `$$` are possible.
      for (const candidate of delims) {
        const startMatchCandidate = src.match(candidate.beginsWithStartDelim);
        if (startMatchCandidate) {
          const length = startMatchCandidate[0].length;
          if (length > longestMatchLength) {
            longestMatchLength = length;
            delim = candidate;
            startMatch = startMatchCandidate;
          }
          break;
        }
      }

      // Bail if we didn't find a delimiter at the beginning.
      if (!delim || !startMatch) {
        return undefined;
      }

      // Get a regular expression for the end delimiter.
      // The pattern must match from the beginning of the string.
      const endDelimReSource = typeof delim.right === 'function' ?
        delim.right(startMatch).source :
        typeof delim.right === 'string' ? escapeRegExp(delim.right) :
        delim.right.source;
      const beginsWithEndDelim = new RegExp(`^${endDelimReSource}`);

      // Go over the rest of the string and try to find the corresponding
      // end delimiter. Once this is found, we also queue the rest of the
      // string for processing, since that might contain additional LaTeX.
      for (let i = startMatch[0].length; i < src.length; i++) {
        const endMatch = src.substring(i).match(beginsWithEndDelim);
        if (endMatch) {
          const content = src.substring(startMatch[0].length, i);
          const raw = src.substring(0, i + endMatch[0].length);
          // Descend into the rest of the string to parse any additional LaTeX.
          const restOfString = src.substring(raw.length);
          if (restOfString.trim().length > 0) {
            // @ts-expect-error: The `lexer` is added by Marked.
            this.lexer.inline(restOfString, []);
          }
          return {
            type: 'katex',
            raw,
            // If `preserve` is specified, keep start and end delimiters.
            content: delim.preserve ? raw : content,
            display: delim.display,
          };
        }
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
    extensions: [markedKatexExtension(opts.delimiters, opts)],
  };
};
