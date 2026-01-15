<script lang="ts">
	import { Select, Button, Label, Input, Heading, Helper, Radio } from 'flowbite-svelte';
	import * as api from '$lib/api';
	import { resolve } from '$app/paths';
	import { writable } from 'svelte/store';
	import { happyToast, sadToast } from '$lib/toast';
	import { goto } from '$app/navigation';
	import AzureLogo from '$lib/components/AzureLogo.svelte';
	import OpenAiLogo from '$lib/components/OpenAILogo.svelte';

	let { data } = $props();

	const loading = writable(false);
	let institutions = $derived(
		(data.admin.canCreateClass || []).sort((a, b) => a.name.localeCompare(b.name))
	);
	let selectedInst = $state('');
	let selectedBilling = $state('0');
	let defaultKeys = $derived(data.defaultKeys || []);

	/**
	 * Create a new class.
	 */
	const submitCreateClass = async (evt: SubmitEvent) => {
		evt.preventDefault();
		$loading = true;

		const form = evt.target as HTMLFormElement;
		const formData = new FormData(form);
		const d = Object.fromEntries(formData.entries());

		const name = d.name?.toString();
		if (!name) {
			$loading = false;
			return sadToast('Name is required');
		}

		const term = d.term?.toString();
		if (!term) {
			$loading = false;
			return sadToast('Session is required');
		}

		let instId = parseInt(d.institution?.toString(), 10);
		if (!instId) {
			const newInst = d.newInstitution?.toString();
			if (!newInst) {
				$loading = false;
				return sadToast('Institution is required');
			}

			const rawInst = await api.createInstitution(fetch, { name: newInst });
			const instResponse = api.expandResponse(rawInst);
			if (instResponse.error) {
				$loading = false;
				return sadToast(instResponse.error.detail || 'Unknown error creating institution');
			}

			instId = instResponse.data.id;

			if (!instId) {
				$loading = false;
				return sadToast('Institution is required');
			}
		}

		let apiKeyId: number | null = parseInt(selectedBilling, 10);
		if (apiKeyId === 0) {
			apiKeyId = null;
		}

		const rawClass = await api.createClass(fetch, instId, { name, term, api_key_id: apiKeyId });
		const classResponse = api.expandResponse(rawClass);
		if (classResponse.error) {
			$loading = false;
			return sadToast(classResponse.error.detail || 'Unknown error creating group');
		}

		$loading = false;
		form.reset();
		happyToast('Group created successfully!');
		await goto(resolve(`/group/${classResponse.data.id}/manage`));
	};
</script>

<div class="flex h-full w-full flex-col items-center gap-8 overflow-auto p-8">
	<Heading tag="h2" class="serif">Create a new group</Heading>
	<form onsubmit={submitCreateClass} class="flex max-w-lg flex-col gap-4 sm:min-w-[32rem]">
		<div>
			<Label for="name" class="mb-1">Name</Label>
			<Input type="text" name="name" id="name" disabled={$loading} />
		</div>
		<div>
			<Label for="term">Session</Label>
			<Helper class="mb-2"
				>Use this field to distinguish between groups that might be reoccuring, such as a class
				being offered every academic year.</Helper
			>
			<Input type="text" name="term" id="term" disabled={$loading} />
		</div>
		<div>
			<Label for="institution" class="mb-1">Institution</Label>
			<Select name="institution" id="institution" bind:value={selectedInst} disabled={$loading}>
				{#each institutions as inst (inst.id)}
					<option value={inst.id}>{inst.name}</option>
				{/each}
				{#if data.admin.canCreateInstitution}
					<option disabled>──────────</option>
					<option value="0">+ Create new</option>
				{/if}
			</Select>
			{#if selectedInst === '0'}
				<div class="pt-4">
					<Label for="newInstitution">Institution name</Label>
					<Input type="text" name="newInstitution" id="new-inst" />
				</div>
			{/if}
		</div>
		<div>
			<Label for="billing">Billing</Label>
			<Helper class="mb-2"
				>Select whether you want to use a pre-configured billing account for access to AI services,
				or set up access later from the Manage Group page. <b
					>If you select a billing account now, you won't be able to change it later.</b
				></Helper
			>
			<div class="flex flex-col gap-2">
				<Radio name="provider" value="0" bind:group={selectedBilling} custom>
					<div
						class="inline-flex w-full min-w-fit cursor-pointer items-center gap-4 rounded-lg border border-gray-200 bg-white px-5 py-3 font-normal text-gray-900 peer-checked:border-red-600 peer-checked:font-medium peer-checked:text-red-600 hover:bg-gray-100 hover:text-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
					>
						<div class="w-full text-base">Set up access later from the Manage Group page.</div>
					</div>
				</Radio>
				{#each defaultKeys as key (key.id)}
					<Radio name="provider" value={key.id} bind:group={selectedBilling} custom>
						<div
							class="inline-flex w-full cursor-pointer items-center gap-4 rounded-lg border border-gray-200 bg-white px-5 py-3 font-normal text-gray-900 peer-checked:border-red-600 peer-checked:font-medium peer-checked:text-red-600 hover:bg-gray-100 hover:text-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
						>
							{#if key.provider === 'azure'}
								<AzureLogo size="8" extraClass="shrink-0" />
							{:else if key.provider === 'openai'}
								<OpenAiLogo size="8" extraClass="shrink-0" />
							{/if}
							<div class="flex flex-col">
								<div class="text-base">
									Use the pre-configured {key.name ?? 'untitled billing'} account.
								</div>
								<div class="font-normal">
									Provider: {key.provider == 'openai'
										? 'OpenAI'
										: key.provider == 'azure'
											? 'Azure'
											: key.provider}
								</div>
								{#if key.endpoint && !key.name}
									<div class="font-normal">Azure endpoint: {key.endpoint}</div>
								{/if}
								{#if !key.name}
									<div class="font-normal">API key: {key.redacted_key}</div>
								{/if}
							</div>
						</div></Radio
					>
				{/each}
			</div>
		</div>
		<div class="flex items-center justify-between">
			<Button
				pill
				outline
				class="border-blue-dark-40 bg-white text-blue-dark-50 hover:bg-blue-light-40 hover:text-blue-dark-50"
				type="reset"
				disabled={$loading}
				href="/admin">Cancel</Button
			>
			<Button
				pill
				class="bg-orange text-white hover:bg-orange-dark"
				type="submit"
				disabled={$loading}>Create</Button
			>
		</div>
	</form>
</div>
