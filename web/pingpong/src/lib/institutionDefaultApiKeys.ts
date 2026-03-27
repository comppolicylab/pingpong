import type { Institution, SetInstitutionDefaultApiKeyRequest } from '$lib/api';

function parseSelectedKeyId(value: string): number | null {
	return value ? Number(value) : null;
}

export function buildInstitutionDefaultApiKeyUpdate(
	institution: Pick<
		Institution,
		| 'default_api_key_id'
		| 'default_lv_narration_tts_api_key_id'
		| 'default_lv_manifest_generation_api_key_id'
	>,
	selectedDefaultKeyId: string,
	selectedDefaultNarrationKeyId: string,
	selectedDefaultManifestKeyId: string
): SetInstitutionDefaultApiKeyRequest {
	const payload: SetInstitutionDefaultApiKeyRequest = {};
	const selectedBillingKeyId = parseSelectedKeyId(selectedDefaultKeyId);
	const selectedNarrationKeyId = parseSelectedKeyId(selectedDefaultNarrationKeyId);
	const selectedManifestKeyId = parseSelectedKeyId(selectedDefaultManifestKeyId);

	if (selectedBillingKeyId !== institution.default_api_key_id) {
		payload.default_api_key_id = selectedBillingKeyId;
	}
	if (selectedNarrationKeyId !== institution.default_lv_narration_tts_api_key_id) {
		payload.default_lv_narration_tts_api_key_id = selectedNarrationKeyId;
	}
	if (selectedManifestKeyId !== institution.default_lv_manifest_generation_api_key_id) {
		payload.default_lv_manifest_generation_api_key_id = selectedManifestKeyId;
	}

	return payload;
}
