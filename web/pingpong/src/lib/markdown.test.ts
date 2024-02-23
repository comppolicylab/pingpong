import { describe, it, expect } from 'vitest';
import { markdown } from './markdown';

describe('markdown', () => {

  it('should render simple markdown', () => {
    expect(markdown(`
Test
===

This is a simple test with a few paragraphs and a list.

- Item 1
- Item 2
- Item 3

This should be inline code \`const x = 1\`.
`)).toBe(`\
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
    expect(markdown(`
Test Code
===
\`\`\`typescript
const x = 1;
\`\`\`
`)).toBe(`\
<h1>Test Code</h1>
<pre><code class="hljs language-typescript"><span class="hljs-keyword">const</span> x = <span class="hljs-number">1</span>;
</code></pre>`);
  });

  it('should render markdown with math', () => {
    expect(markdown(`
Test Math
===
Inline math: $\\frac{1}{2}$
`)).toBe(`\
<h1>Test Math</h1>
<p>Inline math: <span class="katex"><span class="katex-mathml"><math xmlns="http://www.w3.org/1998/Math/MathML"><semantics><mrow><mfrac><mn>1</mn><mn>2</mn></mfrac></mrow><annotation encoding="application/x-tex">\frac{1}{2}</annotation></semantics></math></span><span class="katex-html" aria-hidden="true"><span class="base"><span class="strut" style="height:1.1901em;vertical-align:-0.345em;"></span><span class="mord"><span class="mopen nulldelimiter"></span><span class="mfrac"><span class="vlist-t vlist-t2"><span class="vlist-r"><span class="vlist" style="height:0.8451em;"><span style="top:-2.655em;"><span class="pstrut" style="height:3em;"></span><span class="sizing reset-size6 size3 mtight"><span class="mord mtight"><span class="mord mtight">2</span></span></span></span><span style="top:-3.23em;"><span class="pstrut" style="height:3em;"></span><span class="frac-line" style="border-bottom-width:0.04em;"></span></span><span style="top:-3.394em;"><span class="pstrut" style="height:3em;"></span><span class="sizing reset-size6 size3 mtight"><span class="mord mtight"><span class="mord mtight">1</span></span></span></span></span><span class="vlist-s"></span></span><span class="vlist-r"><span class="vlist" style="height:0.345em;"><span></span></span></span></span></span><span class="mclose nulldelimiter"></span></span></span></span></span></p>
`);
  });

});
