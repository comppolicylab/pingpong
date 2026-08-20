<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import {
		Button,
		Checkbox,
		Heading,
		Helper,
		Input,
		Label,
		MultiSelect,
		Select,
		Spinner,
		Textarea
	} from 'flowbite-svelte';
	import { ArrowRightOutline } from 'flowbite-svelte-icons';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import * as api from '$lib/api';
	import { headerState } from '$lib/stores/header';
	import { happyToast, sadToast } from '$lib/toast';

	export let data;

	const defaultCanvasPreset = data.canvasPlatformPresets.presets.find(
		(preset: api.CanvasPlatformPreset) => preset.id === data.canvasPlatformPresets.default_preset_id
	) as api.CanvasPlatformPreset;

	let sourceRegistrationId = '0';
	let copyingSettings = false;
	let name = '';
	let adminName = '';
	let adminEmail = '';
	let canvasProfile = defaultCanvasPreset.id;
	let issuer = defaultCanvasPreset.issuer;
	let authLoginUrl = defaultCanvasPreset.auth_login_url;
	let authTokenUrl = defaultCanvasPreset.auth_token_url;
	let keySetUrl = defaultCanvasPreset.key_set_url;
	let providerId = api.NO_SSO_PROVIDER_ID_VALUE;
	let ssoField: api.LTISSOField = 'canvas.sisIntegrationId';
	let institutionIds: number[] = [];
	let showInCourseNavigation = true;
	let internalNotes = '';
	let creating = false;

	$: institutionOptions = data.availableInstitutions.map((institution: api.Institution) => ({
		value: institution.id,
		name: institution.name
	}));
	$: usesSso = Number(providerId) !== api.NO_SSO_PROVIDER_ID;
	$: isNewHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	$: if (isNewHeaderLayout) {
		headerState.set({
			kind: 'nongroup',
			props: {
				title: 'LTI Registration',
				redirectUrl: '/admin/lti',
				redirectName: 'All Registrations'
			}
		});
	}

	const detectCanvasProfile = (platform: {
		issuer: string;
		auth_login_url: string;
		auth_token_url: string;
		key_set_url: string;
	}): string => {
		for (const preset of data.canvasPlatformPresets.presets as api.CanvasPlatformPreset[]) {
			if (
				platform.issuer === preset.issuer &&
				platform.auth_login_url === preset.auth_login_url &&
				platform.auth_token_url === preset.auth_token_url &&
				platform.key_set_url === preset.key_set_url
			) {
				return preset.id;
			}
		}
		return 'custom';
	};

	const applyCanvasProfile = (profileId: string) => {
		canvasProfile = profileId;
		if (profileId === 'custom') {
			const currentProfile = detectCanvasProfile({
				issuer,
				auth_login_url: authLoginUrl,
				auth_token_url: authTokenUrl,
				key_set_url: keySetUrl
			});
			if (currentProfile !== 'custom') {
				issuer = '';
				authLoginUrl = '';
				authTokenUrl = '';
				keySetUrl = '';
			}
			return;
		}
		const preset = data.canvasPlatformPresets.presets.find(
			(candidate: api.CanvasPlatformPreset) => candidate.id === profileId
		);
		if (!preset) return;
		issuer = preset.issuer;
		authLoginUrl = preset.auth_login_url;
		authTokenUrl = preset.auth_token_url;
		keySetUrl = preset.key_set_url;
	};

	const resetDraft = () => {
		name = '';
		adminName = '';
		adminEmail = '';
		applyCanvasProfile(data.canvasPlatformPresets.default_preset_id);
		providerId = api.NO_SSO_PROVIDER_ID_VALUE;
		ssoField = 'canvas.sisIntegrationId';
		institutionIds = [];
		showInCourseNavigation = true;
	};

	const applyRegistrationSource = async (registrationId: string) => {
		if (registrationId === '0') {
			resetDraft();
			return;
		}

		copyingSettings = true;
		try {
			const response = api.expandResponse(
				await api.getManualLTIRegistrationTemplate(fetch, registrationId)
			);
			if (sourceRegistrationId !== registrationId) return;
			if (response.error || !response.data) {
				sadToast(response.error?.detail || 'Failed to copy settings');
				return;
			}

			const template = response.data;
			name = template.name;
			adminName = template.admin_name;
			adminEmail = template.admin_email;
			issuer = template.issuer;
			authLoginUrl = template.auth_login_url;
			authTokenUrl = template.auth_token_url;
			keySetUrl = template.key_set_url;
			canvasProfile = detectCanvasProfile(template);

			const hasProvider = data.externalLoginProviders.some(
				(provider: api.ExternalLoginProvider) => provider.id === template.provider_id
			);
			providerId = hasProvider ? `${template.provider_id}` : api.NO_SSO_PROVIDER_ID_VALUE;
			ssoField = template.sso_field ?? 'canvas.sisIntegrationId';
			const availableInstitutionIds = new Set(
				data.availableInstitutions.map((institution: api.Institution) => institution.id)
			);
			institutionIds = template.institution_ids.filter((id) => availableInstitutionIds.has(id));
			showInCourseNavigation = template.show_in_course_navigation;
			happyToast('Settings copied');
		} catch (err) {
			console.error(err);
			sadToast('Failed to copy settings');
		} finally {
			copyingSettings = false;
		}
	};

	const createRegistration = async (event: SubmitEvent) => {
		event.preventDefault();
		if (creating) return;
		if (!name.trim() || !adminName.trim() || !adminEmail.trim()) {
			sadToast('Name and admin contact are required');
			return;
		}
		if (!issuer.trim() || !authLoginUrl.trim() || !authTokenUrl.trim() || !keySetUrl.trim()) {
			sadToast('All Canvas platform fields are required');
			return;
		}
		if (!institutionIds.length) {
			sadToast('Select at least one institution');
			return;
		}

		creating = true;
		try {
			const response = api.expandResponse(
				await api.createManualLTIRegistration(fetch, {
					name: name.trim(),
					admin_name: adminName.trim(),
					admin_email: adminEmail.trim(),
					issuer: issuer.trim(),
					auth_login_url: authLoginUrl.trim(),
					auth_token_url: authTokenUrl.trim(),
					key_set_url: keySetUrl.trim(),
					provider_id: Number(providerId),
					sso_field: usesSso ? ssoField : null,
					institution_ids: institutionIds,
					show_in_course_navigation: showInCourseNavigation,
					internal_notes: internalNotes.trim() || null
				})
			);
			if (response.error || !response.data) {
				sadToast(response.error?.detail || 'Failed to create registration');
				return;
			}
			happyToast('Registration created');
			await goto(resolve(`/admin/lti/${response.data.id}`));
		} catch (err) {
			console.error(err);
			sadToast('Failed to create registration');
		} finally {
			creating = false;
		}
	};
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !isNewHeaderLayout}
		<PageHeader>
			<div slot="left">
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					LTI Registration
				</h2>
			</div>
			<div slot="right">
				<a
					href={resolve('/admin/lti')}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>All Registrations <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
		</PageHeader>
	{/if}

	<div class="w-full space-y-8 p-12">
		<Heading tag="h2" class="text-dark-blue-40 max-w-max shrink-0 font-serif text-3xl font-medium">
			New Manual Registration
		</Heading>

		<form class="max-w-3xl space-y-6" onsubmit={createRegistration}>
			{#if data.sourceRegistrations.length}
				<section
					class="rounded-lg border-2 bg-blue-50 p-4 text-blue-900 sm:p-5 {sourceRegistrationId !==
					'0'
						? 'border-blue-500'
						: 'border-blue-200'}"
				>
					<div class="mb-2 flex items-center gap-2">
						<Label for="source-registration" class="text-lg font-medium text-blue-900">
							Reuse existing settings
						</Label>
						{#if copyingSettings}<Spinner size="4" />{/if}
					</div>
					<Helper class="mb-3 text-blue-900">
						Select a previous registration to copy its Canvas endpoints, contact, SSO, institution,
						and navigation settings. Its client ID is never copied.
					</Helper>
					<Select
						id="source-registration"
						class="bg-white"
						disabled={creating || copyingSettings}
						bind:value={sourceRegistrationId}
						onchange={(event) =>
							applyRegistrationSource((event.currentTarget as HTMLSelectElement).value)}
					>
						<option value="0">Start with new settings</option>
						{#each data.sourceRegistrations as registration (registration.id)}
							<option value={`${registration.id}`}>
								{registration.friendly_name ||
									registration.canvas_account_name ||
									registration.issuer}
								({registration.client_id || 'awaiting client ID'})
							</option>
						{/each}
					</Select>
				</section>
			{/if}

			<div>
				<Label for="registration-name" class="mb-1">Instance name</Label>
				<Input
					id="registration-name"
					bind:value={name}
					placeholder="Example University LMS"
					disabled={creating}
					required
				/>
			</div>

			<div>
				<Label for="admin-name" class="mb-1">Administrator Name</Label>
				<Input
					id="admin-name"
					bind:value={adminName}
					placeholder="John Doe"
					disabled={creating}
					required
				/>
			</div>

			<div>
				<Label for="admin-email" class="mb-1">Administrator Email</Label>
				<Input
					id="admin-email"
					type="email"
					bind:value={adminEmail}
					placeholder="john.doe@example.com"
					disabled={creating}
					required
				/>
			</div>

			<Heading tag="h3" class="text-dark-blue-40 font-serif text-xl font-medium">
				Canvas Platform
			</Heading>

			<div>
				<Label for="canvas-profile" class="mb-1">Canvas Instance</Label>
				<Select
					id="canvas-profile"
					bind:value={canvasProfile}
					disabled={creating}
					onchange={(event) => applyCanvasProfile((event.currentTarget as HTMLSelectElement).value)}
				>
					{#each data.canvasPlatformPresets.presets as preset (preset.id)}
						<option value={preset.id}>{preset.label}</option>
					{/each}
					<option value="custom">Custom Instance, or Self-Hosted</option>
				</Select>
			</div>

			<div>
				<Label for="canvas-issuer" class="mb-1">Issuer</Label>
				<Input
					id="canvas-issuer"
					type="url"
					bind:value={issuer}
					oninput={() => (canvasProfile = 'custom')}
					disabled={creating}
					required
				/>
			</div>

			<div>
				<Label for="canvas-auth-login-url" class="mb-1">OIDC Authorization Redirect URL</Label>
				<Input
					id="canvas-auth-login-url"
					type="url"
					bind:value={authLoginUrl}
					oninput={() => (canvasProfile = 'custom')}
					disabled={creating}
					required
				/>
			</div>

			<div>
				<Label for="canvas-auth-token-url" class="mb-1">OAuth 2 Token URL</Label>
				<Input
					id="canvas-auth-token-url"
					type="url"
					bind:value={authTokenUrl}
					oninput={() => (canvasProfile = 'custom')}
					disabled={creating}
					required
				/>
			</div>

			<div>
				<Label for="canvas-key-set-url" class="mb-1">JWKS URL</Label>
				<Input
					id="canvas-key-set-url"
					type="url"
					bind:value={keySetUrl}
					oninput={() => (canvasProfile = 'custom')}
					disabled={creating}
					required
				/>
			</div>

			<Heading tag="h3" class="text-dark-blue-40 font-serif text-xl font-medium">Settings</Heading>

			<div>
				<Label for="sso-provider" class="mb-1">SSO Provider</Label>
				<Select id="sso-provider" bind:value={providerId} disabled={creating}>
					{#each data.externalLoginProviders as provider (provider.id)}
						<option value={`${provider.id}`}>
							{provider.display_name || provider.name}
						</option>
					{/each}
					<option disabled>──────────</option>
					<option value={api.NO_SSO_PROVIDER_ID_VALUE}>No SSO</option>
				</Select>
			</div>

			{#if usesSso}
				<div>
					<Label for="sso-field" class="mb-1">SSO Field</Label>
					<Select id="sso-field" bind:value={ssoField} disabled={creating}>
						<option value="canvas.sisIntegrationId">Canvas.user.sisIntegrationId</option>
						<option value="canvas.sisSourceId">Canvas.user.sisSourceId</option>
						<option value="person.sourcedId">Person.sourcedId</option>
					</Select>
				</div>
			{/if}

			<div>
				<Label class="mb-1">Institutions</Label>
				{#if institutionOptions.length === 0}
					<p class="text-sm text-gray-500">
						No institutions with default API keys are available to your account.
					</p>
				{:else}
					<MultiSelect
						items={institutionOptions}
						bind:value={institutionIds}
						placeholder="Select institutions..."
						disabled={creating}
					/>
				{/if}
			</div>

			<Checkbox color="blue" bind:checked={showInCourseNavigation} disabled={creating}>
				Show PingPong app in Course Navigation
			</Checkbox>

			<div>
				<Label for="internal-notes" class="mb-1">Internal Notes</Label>
				<Helper class="mb-2">Private notes visible only to admins.</Helper>
				<Textarea id="internal-notes" rows={4} bind:value={internalNotes} disabled={creating} />
			</div>

			<div class="flex items-center justify-between pt-4">
				<Button
					pill
					outline
					class="border-blue-dark-40 bg-white text-blue-dark-50 hover:bg-blue-light-40 hover:text-blue-dark-50"
					href={resolve('/admin/lti')}
					disabled={creating}>Cancel</Button
				>
				<Button
					pill
					type="submit"
					class="bg-orange text-white hover:bg-orange-dark"
					disabled={creating || copyingSettings || !institutionOptions.length}
				>
					{creating ? 'Creating...' : 'Create'}
				</Button>
			</div>
		</form>
	</div>
</div>
