import { error, redirect } from '@sveltejs/kit';
import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch, parent }) => {
	const parentData = await parent();
	if (!parentData.admin?.isRootAdmin) {
		redirect(302, '/');
	}

	const [institutionsResponse, providersResponse, registrationsResponse, presetsResponse] =
		await Promise.all([
			api.getInstitutionsWithDefaultAPIKey(fetch).then(api.expandResponse),
			api.getExternalLoginProviders(fetch).then(api.expandResponse),
			api.getLTIRegistrations(fetch).then(api.expandResponse),
			api.getCanvasPlatformPresets(fetch).then(api.expandResponse)
		]);

	if (institutionsResponse.error || !institutionsResponse.data) {
		error(
			institutionsResponse.$status || 500,
			institutionsResponse.error?.detail || 'Failed to load institutions'
		);
	}
	if (providersResponse.error || !providersResponse.data) {
		error(
			providersResponse.$status || 500,
			providersResponse.error?.detail || 'Failed to load SSO providers'
		);
	}
	if (registrationsResponse.error || !registrationsResponse.data) {
		error(
			registrationsResponse.$status || 500,
			registrationsResponse.error?.detail || 'Failed to load LTI registrations'
		);
	}
	if (presetsResponse.error || !presetsResponse.data) {
		error(
			presetsResponse.$status || 500,
			presetsResponse.error?.detail || 'Failed to load Canvas platform presets'
		);
	}
	if (
		!presetsResponse.data.presets.some(
			(preset) => preset.id === presetsResponse.data!.default_preset_id
		)
	) {
		error(500, 'Canvas platform presets do not include the configured default');
	}

	return {
		availableInstitutions: institutionsResponse.data.institutions,
		externalLoginProviders: providersResponse.data.providers
			.filter((provider) => provider.name !== 'email')
			.sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name)),
		sourceRegistrations: registrationsResponse.data.registrations.sort((a, b) => {
			const aName = a.friendly_name || a.canvas_account_name || a.issuer;
			const bName = b.friendly_name || b.canvas_account_name || b.issuer;
			return aName.localeCompare(bName);
		}),
		canvasPlatformPresets: presetsResponse.data
	};
};
