import type { LTIDeepLinkAssistant } from '$lib/api';
import dayjs from '$lib/time';

export const DEEP_LINK_TITLE = 'Add PingPong to Canvas';
export const DEEP_LINK_SUBTITLE =
	'Choose what content PingPong should show in Canvas for this link.';

export const interactionModeLabel = (mode: LTIDeepLinkAssistant['interaction_mode']) => {
	if (mode === 'lecture_video') return 'Video';
	if (mode === 'lecture_slides') return 'Slides';
	if (mode === 'voice') return 'Voice';
	return 'Chat';
};

export const filterDeepLinkAssistants = (
	assistants: LTIDeepLinkAssistant[],
	search: string
): LTIDeepLinkAssistant[] => {
	const query = search.trim().toLocaleLowerCase();
	if (!query) return assistants;
	return assistants.filter((assistant) =>
		[
			assistant.name,
			assistant.creator_name,
			assistant.description || '',
			interactionModeLabel(assistant.interaction_mode)
		].some((value) => value.toLocaleLowerCase().includes(query))
	);
};

const identityKey = (assistant: LTIDeepLinkAssistant) =>
	`${assistant.name.trim().toLocaleLowerCase()} ${assistant.creator_name
		.trim()
		.toLocaleLowerCase()}`;

/**
 * Assistants whose name and creator both collide with another row, and so need
 * their ID shown to be told apart. The creator is always on screen, so a shared
 * name on its own is not ambiguous.
 */
export const ambiguousAssistantIds = (assistants: LTIDeepLinkAssistant[]): Set<number> => {
	const counts = new Map<string, number>();
	for (const assistant of assistants) {
		const key = identityKey(assistant);
		counts.set(key, (counts.get(key) ?? 0) + 1);
	}
	return new Set(
		assistants
			.filter((assistant) => (counts.get(identityKey(assistant)) ?? 0) > 1)
			.map((assistant) => assistant.id)
	);
};

/** Freshness hint for a picker row, e.g. "Updated 3 days ago". */
export const assistantUpdatedLabel = (updated: string | null): string | null => {
	if (!updated) return null;
	const parsed = dayjs.utc(updated);
	if (!parsed.isValid()) return null;
	return `Updated ${parsed.fromNow()}`;
};

export const ltiSetupQuery = (ltiClassId: number, deepLinkSessionId: number | null) => {
	const params = new URLSearchParams({ lti_class_id: String(ltiClassId) });
	if (deepLinkSessionId !== null) {
		params.set('deep_link_session_id', String(deepLinkSessionId));
	}
	return params.toString();
};
