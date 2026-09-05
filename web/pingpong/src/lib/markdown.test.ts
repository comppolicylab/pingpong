import { describe, it, expect } from 'vitest';
import { markdown } from './markdown';

const normalizeLatexAnnotation = (annotation: string) =>
	annotation.replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();

const getLatexAnnotations = (rendered: string) =>
	[...rendered.matchAll(/<annotation encoding="application\/x-tex">([\s\S]*?)<\/annotation>/g)].map(
		([, annotation]) => normalizeLatexAnnotation(annotation)
	);

const expectLatexAnnotations = (rendered: string, expected: string[]) => {
	expect(getLatexAnnotations(rendered)).toEqual(expected.map(normalizeLatexAnnotation));
};

describe('markdown', () => {
	it('should render simple markdown', () => {
		expect(
			markdown(`
Test
===

This is a simple test with a few paragraphs and a list.

- Item 1
- Item 2
- Item 3

This should be inline code \`const x = 1\`.
`)
		).toBe(`\
<h1>Test</h1>
<p>This is a simple test with a few paragraphs and a list.</p>
<ul>
<li>Item 1</li>
<li>Item 2</li>
<li>Item 3</li>
</ul>
<p>This should be inline code <code>const x = 1</code>.</p>
`);
	});

	it('should render markdown with code', () => {
		expect(
			markdown(`
Test Code
===
\`\`\`typescript
const x = 1;
\`\`\`
`)
		).toBe(`\
<h1>Test Code</h1>
<pre><code class="hljs language-typescript"><span class="hljs-keyword">const</span> x = <span class="hljs-number">1</span>;
</code></pre>`);
	});

	it('should render fenced svg blocks as highlighted code blocks before component mounting', () => {
		const rendered = markdown(`
\`\`\`svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
  <circle cx="5" cy="5" r="4" />
</svg>
\`\`\`
		`);

		expect(rendered).toContain('<pre><code class="hljs language-svg">');
		expect(rendered).toContain('<span class="hljs-name">svg</span>');
		expect(rendered).toContain('<span class="hljs-name">circle</span>');
	});

	it('should render non-document svg fences as code blocks', () => {
		const rendered = markdown(`
\`\`\`svg
<div>not an svg document</div>
\`\`\`
`);

		expect(rendered).toContain('<pre><code class="hljs language-svg">');
	});

	it('should reject unknown markdown options even when they are false', () => {
		markdown('plain text');
		expect(() => markdown('plain text', { unknown: false } as never)).toThrow(
			'Unknown markdown extension: unknown'
		);
	});

	it('should render inline LaTeX with punctuation after it', async () => {
		const rendered = await markdown(`This is $N$'s test.`, { latex: true });

		expect(rendered).toContain('<span class="katex">');
		expect(rendered).toContain('&#39;s test.');
		expectLatexAnnotations(rendered, ['N']);
	});

	it('should not render inline LaTeX when LaTeX rendering is disabled', () => {
		expect(markdown(`This is $N$'s test.`, { latex: false })).toBe(
			`<p>This is $N$&#39;s test.</p>\n`
		);
	});

	it('should render inline LaTeX with other markdown', async () => {
		const rendered = await markdown(
			`
Test Math
===
Inline math: $\\frac{1}{2}$
`,
			{ latex: true }
		);

		expect(rendered).toContain('<h1>Test Math</h1>');
		expect(rendered).toContain('<p>Inline math: <span class="katex">');
		expectLatexAnnotations(rendered, ['\\frac{1}{2}']);
	});

	it('should render invalid inline LaTeX as ordinary escaped text', () => {
		const rendered = markdown('$Soka & Sorrell, 2022, report$', { latex: true });

		expect(rendered).toBe('<p>Soka &amp; Sorrell, 2022, report</p>\n');
		expect(rendered).not.toContain('katex-error');
	});

	it('should render block LaTeX', async () => {
		const rendered = await markdown(
			`
Test Math
===
Here is Ohm's law:

$$
V = IR
$$
`,
			{ latex: true }
		);

		expect(rendered).toContain('<h1>Test Math</h1>');
		expect(rendered).toContain('<p>Here is Ohm&#39;s law:</p>');
		expect(rendered).toContain('<span class="katex-display">');
		expectLatexAnnotations(rendered, ['V = IR']);
	});

	it('should parse a standalone equals sign inside display math before Markdown headings', async () => {
		const rendered = await markdown(
			String.raw`## Example calculation

$$ \text{Average speed}
=
\frac{\text{distance}}{\text{elapsed time}} $$

Use consistent units.`,
			{ latex: true }
		);

		expect(rendered).toContain('<h2>Example calculation</h2>');
		expect(rendered).not.toContain('<h1>');
		expect(rendered).toContain('<span class="katex-display">');
		expectLatexAnnotations(rendered, [
			String.raw`\text{Average speed} = \frac{\text{distance}}{\text{elapsed time}}`
		]);
		expect(rendered).toContain('<p>Use consistent units.</p>');
	});

	it.each([
		['$$', '$$'],
		[String.raw`\[`, String.raw`\]`],
		[String.raw`\begin{equation}`, String.raw`\end{equation}`]
	])('should keep multiline display math intact with %s delimiters', async (left, right) => {
		const equation = 'a\n=\nb\n\n+ c';
		const rendered = await markdown(`${left}\n${equation}\n${right}\n\nAfter.`, { latex: true });

		expect(rendered).toContain('<span class="katex-display">');
		expect(rendered).not.toContain('<h1>');
		expectLatexAnnotations(rendered, [
			left.startsWith('\\begin') ? `${left}\n${equation}\n${right}` : equation
		]);
		expect(rendered).toContain('<p>After.</p>');
	});

	it('should preserve prose following display math on the same line', async () => {
		const rendered = await markdown('$$a = b$$ and then $c$.', { latex: true });

		expect(rendered).toContain('<p><span class="katex-display">');
		expect(rendered).toContain(' and then ');
		expectLatexAnnotations(rendered, ['a = b', 'c']);
	});

	it('should leave math inside code and unclosed display delimiters unrendered', async () => {
		const rendered = await markdown('`$$a = b$$`\n\n```text\n$$a\n=\nb$$\n```\n\n$$unfinished', {
			latex: true,
			syntax: false
		});

		expect(rendered).not.toContain('class="katex');
		expect(rendered).toContain('<code>$$a = b$$</code>');
		expect(rendered).toContain('$$a\n=\nb$$');
		expect(rendered).toContain('<p>$$unfinished</p>');
	});

	it('should render block LaTeX in this test case that failed somehow', async () => {
		const rendered = await markdown(
			`
The 75th percentile, also known as the third quartile, is the value below which 75% of the data falls. To find the 75th percentile in a dataset, you can sort the data in ascending order, then find the position of the 75th percentile using the formula:

$$ P = \\left(\\frac{75}{100} \\times (N + 1)\\right)^{th} \\text{ position} $$

Where \\( N \\) is the number of observations in the dataset. If this formula results in a non-integer value, you interpolate between the surrounding data points. This concept helps in understanding the spread and distribution of policy-relevant data, such as income or test scores, by showing the value below which 75% of the observed population falls.
`,
			{ latex: true }
		);

		expect(rendered).toContain('<span class="katex-display">');
		expect(rendered).toContain('Where <span class="katex">');
		expectLatexAnnotations(rendered, [
			'P = \\left(\\frac{75}{100} \\times (N + 1)\\right)^{th} \\text{ position}',
			'N'
		]);
	});

	it('should render block LaTeX inside a list', async () => {
		const rendered = await markdown(
			`
Test Math
===
- Here is Ohm's law: $$V = IR$$
`,
			{ latex: true }
		);

		expect(rendered).toContain('<h1>Test Math</h1>');
		expect(rendered).toContain('<li>Here is Ohm&#39;s law: <span class="katex-display">');
		expectLatexAnnotations(rendered, ['V = IR']);
	});

	it('should be able to render `\\begin{align*}` blocks as latex', async () => {
		const rendered = await markdown(
			`
**Solution**:
\\begin{align*}
(1 + 2i)(2 - 3i) &= 1 \\cdot 2 + 1 \\cdot (-3i) + 2i \\cdot 2 + 2i \\cdot (-3i) \\\\
&= 2 - 3i + 4i - 6i^2.
\\end{align*}
Since $i^2 = -1$, we get:
$$ 2 - 3i + 4i + 6 = 8 + i.$$
`,
			{ latex: true }
		);

		expect(rendered).toContain('<strong>Solution</strong>');
		expect(rendered.match(/class="katex-display"/g)).toHaveLength(2);
		expectLatexAnnotations(rendered, [
			`\\begin{align*}
(1 + 2i)(2 - 3i) &= 1 \\cdot 2 + 1 \\cdot (-3i) + 2i \\cdot 2 + 2i \\cdot (-3i) \\\\
&= 2 - 3i + 4i - 6i^2.
\\end{align*}`,
			'i^2 = -1',
			'2 - 3i + 4i + 6 = 8 + i.'
		]);
	});
});
