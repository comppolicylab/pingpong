import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';
import { markedKatex } from './marked-katex';
import hljs from 'highlight.js';

/**
 * Markdown renderer with code support.
 */
const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight: (code, lang) => {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext';
      return hljs.highlight(code, { language }).value;
    }
  }),
  markedKatex({ throwOnError: false })
);

/**
 * Convert markdown to HTML.
 */
export const markdown = (markdown: string) => {
  return marked.parse(markdown);
};
