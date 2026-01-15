<script lang="ts">
	import { goto, invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { loading } from '$lib/stores/general';
	import { happyToast, sadToast } from '$lib/toast';
	import {
		Button,
		Heading,
		Helper,
		Hr,
		Input,
		Label,
		MultiSelect,
		Radio,
		Select
	} from 'flowbite-svelte';
	import { ArrowRightOutline, LockSolid } from 'flowbite-svelte-icons';

	let { data } = $props();

	let isCreating = $derived(data.isCreating);
	let agreementPolicyToEdit = $derived(data.agreementPolicy);
	let agreements = $derived(data.agreements);
	let availableAgreements = $derived(agreements.map((agreement) => ({
		value: agreement.id,
		name: agreement.name
	})));
	let externalProviders = $derived(data.externalProviders);
	let availableProviders = $derived(externalProviders.map((provider) => ({
		value: provider.id,
		name: provider.name
	})));

	const handleSubmit = async (event: Event) => {
		event.preventDefault();
		$loading = true;

		const form = event.target as HTMLFormElement;
		const formData = new FormData(form);
		const d = Object.fromEntries(formData.entries());

		const name = d.name?.toString();

		if (!name) {
			$loading = false;
			return sadToast('Please enter a name for the agreement policy.');
		}

		if (!selectedAgreement) {
			$loading = false;
			return sadToast('Please select an agreement.');
		}

		if (selectedTargetGroupValue === '2' && selectedProviders.length === 0) {
			$loading = false;
			return sadToast('Please select at least one external login provider.');
		}

		const params = {
			name,
			agreement_id: selectedAgreement,
			apply_to_all: selectedTargetGroupValue === '1',
			limit_to_providers: selectedTargetGroupValue === '2' ? selectedProviders : null
		};
		const rawAgreement = !agreementPolicyToEdit?.id
			? await api.createAgreementPolicy(fetch, params)
			: await api.updateAgreementPolicy(fetch, agreementPolicyToEdit.id, params);
		const agreementResponse = api.expandResponse(rawAgreement);
		if (agreementResponse.error) {
			$loading = false;
			return sadToast(agreementResponse.error.detail || 'Unknown error saving agreement policy.');
		}
		happyToast('Agreement policy saved successfully!');
		await invalidateAll();
		await goto(resolve(`/admin/terms`));
		$loading = false;
	};

	let selectedAgreement: number | null = $derived(agreementPolicyToEdit?.agreement_id !== undefined ? agreementPolicyToEdit.agreement_id : null);

	let selectedTargetGroupValue = $derived((data.agreementPolicy?.apply_to_all ?? true) ? '1' : '2');
	let selectedProviders = $derived(
		data.agreementPolicy?.limit_to_providers.slice().map((provider) => provider.id) || []
	);

	let preventEdits = $derived(!!agreementPolicyToEdit?.not_before || false);
</script>

<div class="relative flex h-full w-full flex-col">
	<PageHeader>
		{#snippet left()}
				<div >
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					Agreement Policies
				</h2>
			</div>
			{/snippet}
		{#snippet right()}
				<div >
				<a
					href={resolve(`/admin/terms`)}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>All Agreements <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
			{/snippet}
	</PageHeader>
	<div class="h-full w-full overflow-y-auto p-12">
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>{isCreating ? 'Create' : 'Edit'} Agreement Policy</Heading
			>
		</div>
		{#if preventEdits}
			<div
				class="border-gradient-to-r col-span-2 mb-4 flex items-center rounded-lg bg-gradient-to-r from-gray-800 to-gray-600 p-4 text-white"
			>
				<LockSolid class="mr-3 h-8 w-8" />
				<div class="flex w-full flex-row items-center justify-between gap-5">
					<span>
						This Agreement Policy has already been enabled and cannot be edited.<br />To make
						changes, create a new Policy.
					</span>
					<a
						href={resolve(`/admin/terms/policy/new`)}
						class="flex shrink-0 items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-gray-800 hover:text-white"
						>Create Policy <ArrowRightOutline size="md" class="text-orange" /></a
					>
				</div>
			</div>
		{/if}
		<form class="flex flex-col gap-4" onsubmit={handleSubmit}>
			<div>
				<Label for="name" class="mb-1">Agreement Policy Name</Label>
				<Helper class="mb-2"
					>This name will be used to identify agreement policies on the Admin Page and will not be
					displayed to users.</Helper
				>
				<Input
					type="text"
					name="name"
					id="name"
					placeholder="Agreement Policy Name"
					value={agreementPolicyToEdit?.name}
					disabled={$loading || preventEdits}
				/>
			</div>
			<div>
				<Label for="agreement" class="mb-1">Agreement</Label>
				<Helper class="mb-2">Select which agreement to apply to this policy.</Helper>
				<Select
					items={availableAgreements}
					bind:value={selectedAgreement}
					placeholder="Select an agreement..."
					disabled={$loading || preventEdits}
				/>
			</div>
			<div>
				<Label for="options" class="mb-1">Target Group</Label>
				<Helper class="mb-2"
					>Choose whether to show this agreement to all users or display to specific user groups.</Helper
				>
				<div class="flex flex-col gap-2">
					<Radio
						name="targetGroup"
						value="1"
						bind:group={selectedTargetGroupValue}
						disabled={preventEdits || $loading}>Display to all PingPong users.</Radio
					>
					<Radio
						name="targetGroup"
						value="2"
						bind:group={selectedTargetGroupValue}
						disabled={preventEdits || $loading}
						>Only display to users of specific External Login Providers.</Radio
					>
				</div>
			</div>
			{#if selectedTargetGroupValue === '2'}
				<div>
					<Label for="providers" class="mb-1">External Login Providers</Label>
					<Helper class="mb-2"
						>Select which external login providers to display this agreement to.</Helper
					>
					<MultiSelect
						name="providers"
						id="providers"
						bind:value={selectedProviders}
						items={availableProviders}
						disabled={preventEdits || $loading}
					/>
				</div>
			{/if}
			<Hr class="mt-8" />
			<div class="flex flex-row justify-end gap-4">
				<Button
					disabled={$loading}
					href={resolve(`/admin/terms`)}
					pill
					class="rounded-full border border-blue-dark-40 bg-blue-light-50 text-blue-dark-50 hover:bg-blue-light-40"
					>Cancel</Button
				>
				<Button
					pill
					class="border border-orange bg-orange text-white hover:bg-orange-dark"
					type="submit"
					disabled={$loading || preventEdits}>Save</Button
				>
			</div>
		</form>
		<div></div>
	</div>
</div>
