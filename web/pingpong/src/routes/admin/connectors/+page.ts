import type { PageLoad } from './$types';
import * as api from '$lib/api';

export const load: PageLoad = async ({ fetch }) => {
	const [configsResp, servicesResp] = await Promise.all([
		api.getConnectorConfigs(fetch).then(api.expandResponse),
		api.getConnectorServices(fetch).then(api.expandResponse)
	]);

	const configs = configsResp.error ? [] : configsResp.data.configs;
	const services = servicesResp.error ? [] : servicesResp.data.services;

	return {
		connectorConfigs: configs,
		connectorServices: services
	};
};
