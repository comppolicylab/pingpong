<script lang="ts">
	import * as api from '$lib/api';
	import { loading } from '$lib/stores/general';
	import { happyToast, sadToast } from '$lib/toast';
	import { Button, Heading, Helper, Input, Label, Select, Modal } from 'flowbite-svelte';
	import { onMount } from 'svelte';
	import { ExclamationCircleOutline } from 'flowbite-svelte-icons';

	export let data;
	$: externalLoginProviders = data.externalLoginProviders;
	$: institutions = data.institutions || [];

	let openid_configuration: string | null = null;
	let registration_token: string | null = null;
	let missing_params = false;
	let showModal = false;

	let ssoProviderId = '0';
	let institutionIds: number[] = [];

	const isValidSsoField = (value: string): value is api.LTISSOField =>
		value === 'canvas.sisIntegrationId' ||
		value === 'canvas.sisSourceId' ||
		value === 'person.sourcedId';

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		openid_configuration = params.get('openid_configuration');
		registration_token = params.get('registration_token');
		if (!openid_configuration || !registration_token) {
			missing_params = true;
			showModal = true;
		}
	});

	const handleSubmit = async (evt: SubmitEvent) => {
		evt.preventDefault();
		$loading = true;

		const form = evt.target as HTMLFormElement;
		const formData = new FormData(form);
		const name = formData.get('name')?.toString();
		if (!name) {
			$loading = false;
			return sadToast('Name is required');
		}

		const ssoId = formData.get('sso_id')?.toString();
		if (!ssoId) {
			$loading = false;
			return sadToast('SSO identifier is required');
		}
		const providerId = parseInt(ssoId, 10);

		let ssoField: api.LTISSOField | null = null;
		if (providerId !== 0) {
			const rawSsoField = formData.get('sso_field')?.toString()?.trim() ?? '';
			if (!rawSsoField) {
				$loading = false;
				return sadToast('SSO field is required');
			}
			if (!isValidSsoField(rawSsoField)) {
				$loading = false;
				return sadToast('Invalid SSO field');
			}
			ssoField = rawSsoField;
		}

		const adminName = formData.get('admin_name')?.toString();
		if (!adminName) {
			$loading = false;
			return sadToast('Administrator name is required');
		}

		const adminEmail = formData.get('admin_email')?.toString();
		if (!adminEmail) {
			$loading = false;
			return sadToast('Administrator email is required');
		}

		if (!institutionIds.length) {
			$loading = false;
			return sadToast('Select at least one institution');
		}

		const data: api.LTIRegisterRequest = {
			name: name,
			admin_name: adminName,
			admin_email: adminEmail,
			provider_id: providerId,
			sso_field: ssoField,
			openid_configuration: openid_configuration || '',
			registration_token: registration_token || '',
			institution_ids: institutionIds
		};

		const result = await api.registerLTIInstance(fetch, data);
		if (result.$status < 300) {
			happyToast('LTI instance registered successfully');
			window.parent.postMessage({ subject: 'org.imsglobal.lti.close' }, '*');
		} else {
			sadToast('There was an error registering the LTI instance');
		}
		$loading = false;
	};
</script>

<div class="flex h-full w-full flex-col items-center gap-8 overflow-y-auto p-8">
	<Heading tag="h2" class="serif">Set up your LTI instance with PingPong</Heading>
	<form class="flex max-w-lg flex-col gap-4 sm:min-w-[32rem]" onsubmit={handleSubmit}>
		<div>
			<Label for="name" class="mb-1">Instance name</Label>
			<Helper class="mb-2"
				>Use this field to give your LTI instance a name to help us identify it in the future.</Helper
			>
			<Input id="name" name="name" placeholder="Example University LMS" />
		</div>
		<div>
			<Label for="admin_name" class="mb-1">Administrator Name</Label>
			<Helper class="mb-2"
				>Let us know who we should contact if we need to troubleshoot your integration.</Helper
			>
			<Input id="admin_name" name="admin_name" placeholder="John Doe" />
		</div>
		<div>
			<Label for="admin_email" class="mb-1">Administrator Email</Label>
			<Input id="admin_email" name="admin_email" placeholder="john.doe@example.com" type="email" />
		</div>
		<div>
			<Label for="sso_id" class="mb-1">SSO Provider</Label>
			<Helper class="mb-2"
				>Choose the SSO identifier your LTI instance will provide to PingPong. If PingPong doesn’t
				support your SSO identifier, select "No SSO." PingPong will use SSO identifiers and fall
				back to email addresses to identify users.</Helper
			>
			<Select name="sso_id" id="sso_id" disabled={$loading} bind:value={ssoProviderId}>
				{#each externalLoginProviders as provider (provider.id)}
					<option value={provider.id}>{provider.display_name || provider.name}</option>
				{/each}
				<option disabled>──────────</option>
				<option value="0">No SSO</option>
			</Select>
		</div>
		{#if parseInt(ssoProviderId, 10) !== 0}
			<div>
				<Label for="sso_field" class="mb-1">SSO Field</Label>
				<Helper class="mb-2"
					>Select the field where PingPong should expect SSO identifiers. If the field where your
					SSO identifiers are stored isn’t listed, please contact us.</Helper
				>
				<Select name="sso_field" id="sso_field" disabled={$loading}>
					<option value="canvas.sisIntegrationId">Canvas.user.sisIntegrationId</option>
					<option value="canvas.sisSourceId">Canvas.user.sisSourceId</option>
					<option value="person.sourcedId">Person.sourcedId</option>
				</Select>
			</div>
		{/if}
		<div>
			<Label class="mb-1">Institutions</Label>
			<Helper class="mb-2"
				>Select the institutions where your instructors should be able to create groups. When
				PingPong is first launched from Canvas, instructors can either associate an existing group
				from any institution or create a new one in the institutions you’ve selected. If an
				institution you anticipate is not listed, please contact us.</Helper
			>
			{#if institutions.length > 0}
				<div class="max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 p-3">
					<div class="flex flex-col gap-2">
						{#each institutions as inst (inst.id)}
							<label class="flex items-start gap-3">
								<input
									type="checkbox"
									class="mt-1 h-4 w-4 rounded border-gray-300"
									bind:group={institutionIds}
									value={inst.id}
									disabled={$loading}
								/>
								<div class="flex flex-col">
									<div class="text-sm font-medium text-gray-900">{inst.name}</div>
								</div>
							</label>
						{/each}
					</div>
				</div>
			{:else}
				<div class="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">
					No institutions with default API keys are available to your account.
				</div>
			{/if}
		</div>
		<div class="text-sm text-gray-600">
			<b>Note:</b> After completing the LTI registration process, your integration will require review
			by a PingPong staff member before activation. You’ll receive an email notification once your integration
			is approved.
		</div>
		<div class="flex items-center justify-between">
			<Button
				pill
				class="bg-orange text-white hover:bg-orange-dark"
				type="submit"
				disabled={$loading}>Submit</Button
			>
		</div>
	</form>
</div>

<!-- Modal for missing parameters -->
<Modal bind:open={showModal} dismissable={!missing_params} size="md">
	<div class="text-center">
		<div class="mx-auto mb-4 h-14 w-14 text-red-600">
			<ExclamationCircleOutline class="h-14 w-14" />
		</div>
		<h3 class="mb-5 text-lg font-normal text-gray-500">Missing Required Parameters</h3>
		<p class="mb-5 text-sm text-gray-500">
			This page requires both <code class="rounded bg-gray-100 px-1 font-mono"
				>openid_configuration</code
			>
			and <code class="rounded bg-gray-100 px-1 font-mono">registration_token</code> parameters to be
			present in the URL.
		</p>
		<p class="mb-5 text-sm text-gray-500">
			Please ensure you are accessing this page through the proper LTI registration flow.
		</p>
		{#if !missing_params}
			<div class="flex justify-center gap-4">
				<Button color="light" onclick={() => (showModal = false)}>Close</Button>
			</div>
		{/if}
	</div>
</Modal>
