import { describe, expect, it } from 'vitest';
import {
	getAssistantModelModes,
	getEffectiveReasoningEffort,
	getEffectiveTemperature
} from './assistantModelModes';

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

describe('effective assistant reasoning effort', () => {
	it('treats an unset saved effort as the displayed Low value', () => {
		expect(getEffectiveReasoningEffort(null, [-1, 0, 1, 2])).toBe(0);
		expect(getEffectiveReasoningEffort(undefined, [0, 1, 2])).toBe(0);
	});

	it('uses the first supported effort when Low is unavailable', () => {
		expect(getEffectiveReasoningEffort(null, [1, 2])).toBe(1);
		expect(getEffectiveReasoningEffort(0, [2])).toBe(2);
	});

	it('preserves explicit saved choices and distinguishes changed efforts', () => {
		expect(getEffectiveReasoningEffort(-1, [-1, 0, 1, 2])).toBe(-1);
		expect(getEffectiveReasoningEffort(2, [0, 1, 2])).toBe(2);
		expect(getEffectiveReasoningEffort(null, [0, 1, 2])).not.toBe(1);
	});
});

describe('effective assistant temperature', () => {
	it('matches the voice default for an unset saved temperature', () => {
		expect(getEffectiveTemperature(null, true, 0.8)).toBe(0.8);
		expect(getEffectiveTemperature(undefined, true, 0.8)).toBe(0.8);
	});

	it('ignores legacy temperatures when the selected model has no temperature control', () => {
		expect(getEffectiveTemperature(0.8, false, 0.8)).toBeNull();
	});

	it('preserves explicit temperatures, including zero, and detects user changes', () => {
		expect(getEffectiveTemperature(0, true, 0.2)).toBe(0);
		expect(getEffectiveTemperature(1, true, 0.8)).toBe(1);
		expect(getEffectiveTemperature(null, true, 0.8)).not.toBe(0.9);
	});
});
