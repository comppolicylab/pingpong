import { describe, expect, it } from 'vitest';

import { buildInstitutionDefaultApiKeyUpdate } from '$lib/institutionDefaultApiKeys';

describe('buildInstitutionDefaultApiKeyUpdate', () => {
	it('omits unchanged fields from the request payload', () => {
		expect(
			buildInstitutionDefaultApiKeyUpdate(
				{
					default_api_key_id: 10,
					default_lv_narration_tts_api_key_id: 20,
					default_lv_manifest_generation_api_key_id: 30
				},
				'10',
				'21',
				'30'
			)
		).toEqual({
			default_lv_narration_tts_api_key_id: 21
		});
	});

	it('sends null when a key is explicitly cleared', () => {
		expect(
			buildInstitutionDefaultApiKeyUpdate(
				{
					default_api_key_id: 10,
					default_lv_narration_tts_api_key_id: 20,
					default_lv_manifest_generation_api_key_id: 30
				},
				'',
				'20',
				''
			)
		).toEqual({
			default_api_key_id: null,
			default_lv_manifest_generation_api_key_id: null
		});
	});
});
