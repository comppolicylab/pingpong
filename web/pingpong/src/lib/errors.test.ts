import { describe, expect, it, vi } from 'vitest';

import { errorMessage } from './errors';

describe('errorMessage', () => {
	it('extracts the detail returned by a failed file upload', () => {
		const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

		expect(
			errorMessage({
				error: { detail: 'Inserted video clips must include an audio track.' }
			})
		).toBe('Inserted video clips must include an audio track.');

		consoleError.mockRestore();
	});
});
