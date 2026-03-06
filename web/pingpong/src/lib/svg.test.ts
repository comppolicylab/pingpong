import { describe, expect, it } from 'vitest';
import { getSvgFenceClosureStates } from './svg';

describe('getSvgFenceClosureStates', () => {
	it('marks closed svg fences as complete', () => {
		expect(
			getSvgFenceClosureStates(`
\`\`\`svg
<svg viewBox="0 0 10 10"></svg>
\`\`\`
`)
		).toEqual([true]);
	});

	it('marks an unclosed trailing svg fence as incomplete', () => {
		expect(
			getSvgFenceClosureStates(`
\`\`\`svg
<svg viewBox="0 0 10 10"></svg>
`)
		).toEqual([false]);
	});

	it('tracks multiple svg fences and ignores other languages', () => {
		expect(
			getSvgFenceClosureStates(`
\`\`\`svg
<svg viewBox="0 0 10 10"></svg>
\`\`\`

\`\`\`typescript
const svg = false;
\`\`\`

\`\`\`image/svg+xml
<svg viewBox="0 0 20 20"></svg>
\`\`\`

\`\`\`svg
<svg viewBox="0 0 30 30"></svg>
`)
		).toEqual([true, true, false]);
	});
});
