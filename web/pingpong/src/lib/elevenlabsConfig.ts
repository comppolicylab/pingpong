import type { Assistant, ElevenLabsConfig, ElevenLabsTTSProfile } from '$lib/api';

export const DEFAULT_FLASH_PROFILE: ElevenLabsTTSProfile = {
	model: 'eleven_flash_v2_5',
	stability: 0.5,
	similarity_boost: 0.8,
	use_speaker_boost: true,
	style: 0,
	speed: 1
};

export const DEFAULT_V3_PROFILE: ElevenLabsTTSProfile = {
	...DEFAULT_FLASH_PROFILE,
	model: 'eleven_v3'
};

const copyProfile = (profile: ElevenLabsTTSProfile): ElevenLabsTTSProfile => ({ ...profile });

export const newElevenLabsConfig = (): ElevenLabsConfig => ({
	version: 1,
	narration: copyProfile(DEFAULT_V3_PROFILE),
	knowledge_check: copyProfile(DEFAULT_V3_PROFILE),
	live_chat: copyProfile(DEFAULT_FLASH_PROFILE)
});

export const legacyElevenLabsConfig = (assistant: Assistant): ElevenLabsConfig => ({
	version: 1,
	narration: copyProfile(DEFAULT_V3_PROFILE),
	knowledge_check: copyProfile(DEFAULT_V3_PROFILE),
	live_chat: {
		model: 'eleven_flash_v2_5',
		stability: assistant.elevenlabs_stability ?? DEFAULT_FLASH_PROFILE.stability,
		similarity_boost:
			assistant.elevenlabs_similarity_boost ?? DEFAULT_FLASH_PROFILE.similarity_boost,
		use_speaker_boost:
			assistant.elevenlabs_use_speaker_boost ?? DEFAULT_FLASH_PROFILE.use_speaker_boost,
		style: assistant.elevenlabs_style ?? DEFAULT_FLASH_PROFILE.style,
		speed: assistant.elevenlabs_speed ?? DEFAULT_FLASH_PROFILE.speed
	}
});

export const configForAssistant = (assistant: Assistant | null | undefined): ElevenLabsConfig => {
	if (!assistant) return newElevenLabsConfig();
	const config = assistant.elevenlabs_config ?? legacyElevenLabsConfig(assistant);
	return {
		version: 1,
		narration: copyProfile(config.narration),
		knowledge_check: copyProfile(config.knowledge_check),
		live_chat: copyProfile(config.live_chat)
	};
};
