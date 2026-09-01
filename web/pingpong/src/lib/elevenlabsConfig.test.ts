import { describe, expect, it } from 'vitest';
import type { Assistant } from '$lib/api';
import {
	configForAssistant,
	legacyElevenLabsConfig,
	newElevenLabsConfig
} from '$lib/elevenlabsConfig';

describe('ElevenLabs component configuration', () => {
	it('defaults generated audio to v3 and live chat to Flash', () => {
		const config = newElevenLabsConfig();
		expect(config.narration.model).toBe('eleven_v3');
		expect(config.knowledge_check.model).toBe('eleven_v3');
		expect(config.live_chat.model).toBe('eleven_flash_v2_5');
		expect(config.narration).not.toBe(config.knowledge_check);
	});

	it('maps legacy generation to v3 while preserving surfaced Flash chat settings', () => {
		const assistant = {
			elevenlabs_config: null,
			elevenlabs_stability: 0.9,
			elevenlabs_similarity_boost: 0.4,
			elevenlabs_use_speaker_boost: false,
			elevenlabs_style: 0.2,
			elevenlabs_speed: 1.1
		} as Assistant;
		const config = legacyElevenLabsConfig(assistant);

		expect(config.narration.model).toBe('eleven_v3');
		expect(config.knowledge_check.model).toBe('eleven_v3');
		expect(config.knowledge_check.stability).toBe(0.5);
		expect(config.live_chat).toMatchObject({
			model: 'eleven_flash_v2_5',
			stability: 0.9,
			use_speaker_boost: false,
			speed: 1.1
		});
	});

	it('copies persisted profiles so editor changes stay independent', () => {
		const assistant = {
			elevenlabs_config: newElevenLabsConfig()
		} as Assistant;
		const config = configForAssistant(assistant);

		expect(config.narration).not.toBe(assistant.elevenlabs_config?.narration);
		expect(config.live_chat).not.toBe(config.narration);
	});
});
