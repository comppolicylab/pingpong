import { describe, expect, it } from 'vitest';
import { parseMarkdownSegments } from './markdown-segments';

describe('parseMarkdownSegments', () => {
	it('keeps diagram fences literal when they appear inside another fenced code block', () => {
		const segments = parseMarkdownSegments(
			`
\`\`\`\`md
\`\`\`mermaid
graph TD
  A-->B
\`\`\`
\`\`\`\`
`,
			{ syntax: true, latex: false }
		);

		expect(segments).toHaveLength(1);
		expect(segments[0].type).toBe('html');
		if (segments[0].type !== 'html') {
			throw new Error(`Expected html segment, got ${segments[0].type}`);
		}
		expect(segments[0].content).toContain('language-md');
		expect(segments[0].content).toContain('```mermaid');
		expect(segments[0].content).toContain('A--&gt;B');
	});

	it('preserves list context around mermaid segments', () => {
		const segments = parseMarkdownSegments(
			`
- before

  \`\`\`mermaid
  graph TD
  A-->B
  \`\`\`

  after
`,
			{ syntax: true, latex: false }
		);

		expect(segments).toHaveLength(3);
		expect(segments[0]).toMatchObject({ type: 'html' });
		expect(segments[1]).toMatchObject({
			type: 'wrapped-diagram',
			diagram: { type: 'mermaid-complete', source: 'graph TD\nA-->B' }
		});
		expect(segments[2]).toMatchObject({ type: 'html' });
		expect(segments[0].type === 'html' && segments[0].content).toContain('<ul>');
		expect(segments[0].type === 'html' && segments[0].content).toContain('<li><p>before</p>');
		expect(segments[1].type === 'wrapped-diagram' && segments[1].content).toContain('<ul>');
		expect(segments[2].type === 'html' && segments[2].content).toContain('<ul>');
		expect(segments[2].type === 'html' && segments[2].content).toContain('<li><p>after</p>');
	});

	it('preserves list context around svg segments', () => {
		const segments = parseMarkdownSegments(
			`
- before

  \`\`\`svg
  <svg viewBox="0 0 10 10"></svg>
  \`\`\`

  after
`,
			{ syntax: true, latex: false }
		);

		expect(segments).toHaveLength(3);
		expect(segments[0]).toMatchObject({ type: 'html' });
		expect(segments[1]).toMatchObject({
			type: 'wrapped-diagram',
			diagram: { type: 'svg-complete', source: '<svg viewBox="0 0 10 10"></svg>' }
		});
		expect(segments[2]).toMatchObject({ type: 'html' });
		expect(segments[0].type === 'html' && segments[0].content).toContain('<ul>');
		expect(segments[0].type === 'html' && segments[0].content).toContain('<li><p>before</p>');
		expect(segments[1].type === 'wrapped-diagram' && segments[1].content).toContain('<ul>');
		expect(segments[2].type === 'html' && segments[2].content).toContain('<ul>');
		expect(segments[2].type === 'html' && segments[2].content).toContain('<li><p>after</p>');
	});

	it('preserves blockquote context around diagram segments', () => {
		const segments = parseMarkdownSegments(
			`
> \`\`\`mermaid
> graph TD
> A-->B
> \`\`\`
`,
			{ syntax: true, latex: false }
		);

		expect(segments).toHaveLength(1);
		expect(segments[0]).toMatchObject({
			type: 'wrapped-diagram',
			diagram: { type: 'mermaid-complete', source: 'graph TD\nA-->B' }
		});
		expect(segments[0].type === 'wrapped-diagram' && segments[0].content).toContain('<blockquote>');
	});

	it('returns svg-streaming for an unclosed svg fence', () => {
		const segments = parseMarkdownSegments(
			`
\`\`\`svg
<svg viewBox="0 0 10 10"></svg>
`,
			{ syntax: true, latex: false }
		);

		expect(segments).toEqual([
			{ type: 'svg-streaming', source: '<svg viewBox="0 0 10 10"></svg>' }
		]);
	});
});
