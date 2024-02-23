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
    expect(markdown(`This is $N$'s test.`)).toBe(
      `<p>This is <span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mrow><mi>N</mi></mrow><annotation encoding="application/x-tex">N</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:0.6833em;"></span><span class="mord mathnormal" style="margin-right:0.10903em;">N</span></span></span></span>&#39;s test.</p>
`
    );
  });

  it('should render inline LaTeX with other markdown', () => {
    expect(
      markdown(`
Test Math
===
Inline math: $\\frac{1}{2}$
`)
    ).toMatchSnapshot();
  });

  it('should render block LaTeX', () => {
    expect(
      markdown(`
Test Math
===
Here is Ohm's law:

$$
V = IR
$$
`)
    ).toMatchSnapshot();
  });

  it('should render block LaTeX inside a list', () => {
    expect(
      markdown(`
Test Math
===
- Here is Ohm's law: $$V = IR$$
`)
    ).toMatchSnapshot();
  });
});
