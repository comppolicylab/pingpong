import { describe, expect, it, vi } from 'vitest';

import type { LTIDeepLinkAssistant } from './api';
import {
	ambiguousAssistantIds,
	assistantUpdatedLabel,
	filterDeepLinkAssistants,
	interactionModeLabel
} from './ltiDeepLink';

const assistants: LTIDeepLinkAssistant[] = [
	{
		id: 1,
		name: 'Study Coach',
		description: 'Reviews weekly concepts',
		interaction_mode: 'chat',
		creator_name: 'Ada Lovelace',
		avatar_url: null,
		endorsed: true,
		updated: null
	},
	{
		id: 2,
		name: 'Lab Guide',
		description: null,
		interaction_mode: 'lecture_slides',
		creator_name: 'Grace Hopper',
		avatar_url: null,
		endorsed: false,
		updated: null
	}
];

describe('Canvas Deep Linking picker helpers', () => {
	it('searches assistant names, creators, and descriptions locally', () => {
		expect(filterDeepLinkAssistants(assistants, 'weekly').map((assistant) => assistant.id)).toEqual(
			[1]
		);
		expect(filterDeepLinkAssistants(assistants, 'hopper').map((assistant) => assistant.id)).toEqual(
			[2]
		);
	});

	it('searches the interaction type shown on each row', () => {
		expect(filterDeepLinkAssistants(assistants, 'slides').map((assistant) => assistant.id)).toEqual(
			[2]
		);
	});

	it('uses compact user-facing interaction labels', () => {
		expect(interactionModeLabel('lecture_slides')).toBe('Slides');
		expect(interactionModeLabel('chat')).toBe('Chat');
	});

	it('only disambiguates by ID when the name and creator both collide', () => {
		const sameNameDifferentCreator: LTIDeepLinkAssistant = {
			...assistants[0],
			id: 3,
			creator_name: 'Grace Hopper'
		};
		const sameNameSameCreator: LTIDeepLinkAssistant = { ...assistants[0], id: 4 };
		expect(ambiguousAssistantIds([...assistants, sameNameDifferentCreator])).toEqual(new Set());
		expect(ambiguousAssistantIds([...assistants, sameNameSameCreator])).toEqual(new Set([1, 4]));
	});

	it('labels freshness only when the assistant has a timestamp', () => {
		vi.useFakeTimers();
		try {
			vi.setSystemTime(new Date('2026-06-15T12:00:00Z'));
			expect(assistantUpdatedLabel(null)).toBeNull();
			expect(assistantUpdatedLabel('not a date')).toBeNull();
			expect(assistantUpdatedLabel(new Date(Date.now() - 3 * 86_400_000).toISOString())).toBe(
				'Updated 3 days ago'
			);
		} finally {
			vi.useRealTimers();
		}
	});
});
