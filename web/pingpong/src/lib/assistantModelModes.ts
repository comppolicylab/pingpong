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
