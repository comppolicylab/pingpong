import { describe, expect, it } from 'vitest';
import { getAssistantModelModes } from './assistantModelModes';

describe('assistant model modes', () => {
	it('does not offer voice creation when only hidden or unavailable voice models remain', () => {
		expect(
			getAssistantModelModes([
				{ type: 'chat', is_available: true },
				{ type: 'voice', is_available: false, hide_in_model_selector: true },
				{ type: 'voice', is_available: true, hide_in_model_selector: true },
				{ type: 'voice', is_available: false }
			])
		).toEqual({ chat: true, voice: false });
	});

	it('offers voice when a visible voice model is available', () => {
		expect(getAssistantModelModes([{ type: 'voice', is_available: true }])).toEqual({
			chat: false,
			voice: true
		});
	});

	it('preserves an existing voice assistant mode when no voice models are selectable', () => {
		expect(getAssistantModelModes([{ type: 'chat' }], 'voice')).toEqual({
			chat: true,
			voice: true
		});
	});

	it('preserves an existing chat assistant mode when no chat models are selectable', () => {
		expect(getAssistantModelModes([], 'chat')).toEqual({ chat: true, voice: false });
	});

	it('accepts older model metadata without availability fields', () => {
		expect(getAssistantModelModes([{ type: 'chat' }, { type: 'voice' }])).toEqual({
			chat: true,
			voice: true
		});
	});
});
