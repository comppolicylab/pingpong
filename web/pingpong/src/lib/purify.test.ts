import { describe, it, expect } from 'vitest';
import purify from './purify';

describe('purify', () => {
	it('should add target blank and proper rel to links', () => {
		expect(purify.sanitize(`<a href="https://pingpong.local/">pingpong</a>`)).toBe(
			`<a href="https://pingpong.local/" target="_blank" rel="noopener noreferrer external">pingpong</a>`
		);
	});

	it('should not add target blank and proper rel to non-links', () => {
		expect(purify.sanitize('<div>pingpong</div>')).toBe('<div>pingpong</div>');
	});

	it('should preserve safe svg content while removing unsafe svg tags', () => {
		expect(
			purify.sanitize(
				'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><script>alert(1)</script><foreignObject width="10" height="10"><div xmlns="http://www.w3.org/1999/xhtml">unsafe</div></foreignObject><circle cx="5" cy="5" r="4" /></svg>'
			)
		).toBe(
			'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"></circle></svg>'
		);
	});
});
