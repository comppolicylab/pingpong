import { type Text, join } from '$lib/api';

type Replacement = {
  start: number;
  end: number;
  newValue: string;
};

/**
 * Rewrite OpenAI text content to incorporate annotations.
 */
export const parseTextContent = (text: Text, baseUrl: string = '') => {
  let content = text.value;
  const replacements: Replacement[] = [];
  if (text.annotations) {
    for (const annotation of text.annotations) {
      if (annotation.type === 'file_path') {
        const { start_index, end_index, file_path } = annotation;
        const url = join(baseUrl, `/file/${file_path.file_id}`);
        replacements.push({ start: start_index, end: end_index, newValue: url });
      } else if (annotation.type === 'file_citation') {
        const { start_index, end_index, file_citation } = annotation;
        const fileName = ` (${file_citation.file_name})`;
        replacements.push({ start: start_index, end: end_index, newValue: fileName });
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

  return content;
};

/**
 * Normalize newlines to use only '\n'.
 */
export const normalizeNewlines = (text: string) => text.replace(/\r\n/g, '\n');
