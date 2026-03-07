import { describe, expect, it } from 'vitest';
import { SVG_DOCUMENT_PATTERN, parseDiagramFence } from './diagram';

describe('SVG_DOCUMENT_PATTERN', () => {
	it('matches a complete svg document', () => {
		expect(
			SVG_DOCUMENT_PATTERN.test(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
  <circle cx="5" cy="5" r="4" />
</svg>
`)
		).toBe(true);
	});

	it('matches an svg document with an xml declaration', () => {
		expect(
			SVG_DOCUMENT_PATTERN.test(
				`<?xml version="1.0" encoding="UTF-8"?><svg viewBox="0 0 10 10"></svg>`
			)
		).toBe(true);
	});

	it('rejects non-svg markup', () => {
		expect(SVG_DOCUMENT_PATTERN.test('<div>not an svg</div>')).toBe(false);
	});

	it('parses svg fences into the shared diagram shape', () => {
		expect(
			parseDiagramFence(
				'svg',
				'```svg\n<svg viewBox="0 0 10 10"></svg>\n```',
				'<svg viewBox="0 0 10 10"></svg>'
			)
		).toEqual({
			kind: 'svg',
			state: 'complete',
			source: '<svg viewBox="0 0 10 10"></svg>'
		});
	});
});
