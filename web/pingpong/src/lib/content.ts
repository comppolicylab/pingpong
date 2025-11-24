import { join, type Text, type WebSearchSource } from '$lib/api';

type Replacement = {
  start: number;
  end: number;
  newValue: string;
};

export type InlineWebSource = {
  index: number;
  source: WebSearchSource;
};

export type ParsedTextContent = {
  content: string;
  inlineWebSources: InlineWebSource[];
};

/**
 * Rewrite OpenAI text content to incorporate annotations.
 */
export const parseTextContent = (
  text: Text,
  threadVersion: number = 2,
  baseUrl: string = ''
): ParsedTextContent => {
  let content = text.value;
  const replacements: Replacement[] = [];
  const inlineWebSources: InlineWebSource[] = [];
  let urlCitationIndex = 0;
  if (text.annotations) {
    for (const annotation of text.annotations) {
      if (
        annotation.type === 'file_path' &&
        ((!annotation.file_path.file_id.startsWith('cfile_') && threadVersion === 3) ||
          threadVersion === 2)
      ) {
        const { start_index, end_index, file_path } = annotation;
        const url = join(baseUrl, `/file/${file_path.file_id}`);
        replacements.push({ start: start_index, end: end_index, newValue: url });
      } else if (annotation.type === 'file_citation' && annotation.text !== 'responses_v3') {
        const { start_index, end_index, file_citation } = annotation;
        const fileName = ` (${file_citation.file_name})`;
        replacements.push({ start: start_index, end: end_index, newValue: fileName });
      } else if (annotation.type === 'url_citation') {
        // Drop a placeholder that the Markdown component swaps for an inline WebSourceChip.
        inlineWebSources.push({
          index: urlCitationIndex,
          source: {
            url: annotation.url,
            title: annotation.title || undefined,
            type: 'url'
          }
        });
        const needsLeadingSpace =
          annotation.start_index > 0 && !/\s/.test(text.value[annotation.start_index - 1]);
        replacements.push({
          start: annotation.start_index,
          end: annotation.end_index,
          newValue: `${needsLeadingSpace ? ' ' : ''}<span data-web-source-index="${urlCitationIndex}"></span>`
        });
        urlCitationIndex += 1;
      }
    }
  }

  // Apply replacements in reverse order (so that the indexes are still valid
  // while we are modifying the content).
  replacements.sort((a, b) => b.start - a.start);
  for (let i = 0; i < replacements.length; i++) {
    const { start, end, newValue } = replacements[i];
    content = content.slice(0, start) + newValue + content.slice(end);
  }

  return { content, inlineWebSources };
};

/**
 * Normalize newlines to use only '\n'.
 */
export const normalizeNewlines = (text: string) => text.replace(/\r\n/g, '\n');
