import type { AssistantModel } from './api';

export function getAssistantModelModes(
	models: Pick<AssistantModel, 'type' | 'is_available' | 'hide_in_model_selector'>[],
	savedMode?: string | null
) {
	const selectableModels = models.filter(
		(model) => model.is_available !== false && !model.hide_in_model_selector
	);
	return {
		chat: savedMode === 'chat' || selectableModels.some((model) => model.type === 'chat'),
		voice: savedMode === 'voice' || selectableModels.some((model) => model.type === 'voice')
	};
}

/** Resolve a saved effort to the value shown by the assistant editor. */
export function getEffectiveReasoningEffort(
	savedEffort: number | null | undefined,
	levels: number[]
): number {
	const effort = savedEffort ?? 0;
	return levels.includes(effort) ? effort : (levels[0] ?? 0);
}

/** Match the temperature control's default and model capability. */
export function getEffectiveTemperature(
	savedTemperature: number | null | undefined,
	supportsTemperature: boolean,
	defaultTemperature: number
): number | null {
	return supportsTemperature ? (savedTemperature ?? defaultTemperature) : null;
}
