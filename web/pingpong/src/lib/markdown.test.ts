import { describe, it, expect } from 'vitest';
import { markdown } from './markdown';

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

  it('should render inline LaTeX with punctuation after it', () => {
    expect(markdown(`This is $N$'s test.`, { latex: true })).toBe(
      `<p>This is <span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mrow><mi>N</mi></mrow><annotation encoding="application/x-tex">N</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:0.6833em;"></span><span class="mord mathnormal" style="margin-right:0.10903em;">N</span></span></span></span>&#39;s test.</p>
`
    );
  });

  it('should not render inline LaTeX when LaTeX rendering is disabled', () => {
    expect(markdown(`This is $N$'s test.`, { latex: false })).toBe(
      `<p>This is $N$&#39;s test.</p>\n`
    );
  });

  it('should render inline LaTeX with other markdown', () => {
    expect(
      markdown(
        `
Test Math
===
Inline math: $\\frac{1}{2}$
`,
        { latex: true }
      )
    ).toMatchSnapshot();
  });

  it('should render block LaTeX', () => {
    expect(
      markdown(
        `
Test Math
===
Here is Ohm's law:

$$
V = IR
$$
`,
        { latex: true }
      )
    ).toMatchSnapshot();
  });

  it('should render block LaTeX in this test case that failed somehow', () => {
    expect(
      markdown(
        `
The 75th percentile, also known as the third quartile, is the value below which 75% of the data falls. To find the 75th percentile in a dataset, you can sort the data in ascending order, then find the position of the 75th percentile using the formula:

$$ P = \\left(\\frac{75}{100} \\times (N + 1)\\right)^{th} \\text{ position} $$

Where \\( N \\) is the number of observations in the dataset. If this formula results in a non-integer value, you interpolate between the surrounding data points. This concept helps in understanding the spread and distribution of policy-relevant data, such as income or test scores, by showing the value below which 75% of the observed population falls.
`,
        { latex: true }
      )
    ).toMatchSnapshot();
  });

  it('should render block LaTeX inside a list', () => {
    expect(
      markdown(
        `
Test Math
===
- Here is Ohm's law: $$V = IR$$
`,
        { latex: true }
      )
    ).toMatchSnapshot();
  });

  it('should be able to render `\\begin{align*}` blocks as latex', () => {
    expect(
      markdown(
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
      )
    ).toMatchSnapshot();
  });
});
