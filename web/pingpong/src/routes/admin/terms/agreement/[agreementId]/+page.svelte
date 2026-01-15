<script lang="ts">
	import { run } from 'svelte/legacy';

	import { goto, invalidateAll } from '$app/navigation';
	import * as api from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { loading } from '$lib/stores/general';
	import { happyToast, sadToast } from '$lib/toast';
	import { Button, Heading, Helper, Hr, Input, Label, Textarea } from 'flowbite-svelte';
	import { ArrowRightOutline, LockSolid } from 'flowbite-svelte-icons';
	import Modal from '$lib/components/CustomModal.svelte';
	import { resolve } from '$app/paths';

	let { data } = $props();

	let isCreating = $derived(data.isCreating);
	let userAgreementToEdit = $derived(data.userAgreement);

	const handleSubmit = async (event: Event) => {
		event.preventDefault();
		$loading = true;

		const form = event.target as HTMLFormElement;
		const formData = new FormData(form);
		const d = Object.fromEntries(formData.entries());

		const name = d.name?.toString();
		const code = d.code?.toString();

		const params = {
			name,
			body: code
		};
		const rawAgreement = !userAgreementToEdit?.id
			? await api.createAgreement(fetch, params)
			: await api.updateAgreement(fetch, userAgreementToEdit.id, params);
		const agreementResponse = api.expandResponse(rawAgreement);
		if (agreementResponse.error) {
			$loading = false;
			return sadToast(agreementResponse.error.detail || 'Unknown error saving agreement.');
		}
		happyToast('Agreement saved successfully!');
		await invalidateAll();
		await goto(resolve(`/admin/terms`));
		$loading = false;
	};

	let showCodeModal = $state(false);
	let code = $state('');
	run(() => {
		if (userAgreementToEdit?.body && !code) {
			code = userAgreementToEdit.body;
		}
	});

	let preventEdits = $derived(userAgreementToEdit?.policies && userAgreementToEdit.policies.length > 0);
</script>

<div class="relative flex h-full w-full flex-col">
	<PageHeader>
		{#snippet left()}
				<div >
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					User Agreements
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
				>{isCreating ? 'Create' : 'Edit'} User Agreement</Heading
			>
		</div>
		{#if preventEdits}
			<div
				class="border-gradient-to-r col-span-2 mb-4 flex items-center rounded-lg bg-gradient-to-r from-gray-800 to-gray-600 p-4 text-white"
			>
				<LockSolid class="mr-3 h-8 w-8" />
				<div class="flex w-full flex-row items-center justify-between gap-5">
					<span>
						This Agreement is associated with one or more Agreement Policies and cannot be edited.<br
						/>To make changes, create a new Agreement.
					</span>
					<a
						href={resolve(`/admin/terms/agreement/new`)}
						class="flex shrink-0 items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-gray-800 hover:text-white"
						>Create Agreement <ArrowRightOutline size="md" class="text-orange" /></a
					>
				</div>
			</div>
		{/if}
		<form class="flex flex-col gap-4" onsubmit={handleSubmit}>
			<div>
				<Label for="name" class="mb-1">Agreement Name</Label>
				<Helper class="mb-2"
					>This name will be used to identify user agreements on the Admin Page and will not be
					displayed to users.</Helper
				>
				<Input
					type="text"
					name="name"
					id="name"
					placeholder="Agreement Name"
					value={userAgreementToEdit?.name}
					disabled={$loading || preventEdits}
				/>
			</div>
			<div>
				<div class="mb-1 flex flex-row items-end justify-between">
					<Label for="code">Agreement Content</Label><Button
						pill
						size="sm"
						class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white px-3 py-0.5 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
						disabled={$loading}
						onclick={() => (showCodeModal = true)}
					>
						{preventEdits ? 'Preview' : 'Edit with Preview'}
					</Button>
				</div>
				<Helper class="mb-2"
					>This is the HTML code that will be displayed to users. You can use the <a
						href="https://flowbite-svelte.com"
						target="_blank"
						class="text-blue-dark-40 hover:text-blue-dark-50">Flowbite Svelte</a
					> components to style your agreement.</Helper
				>
				<Textarea
					name="code"
					id="code"
					bind:value={code}
					class="font-mono"
					rows={10}
					disabled={$loading || preventEdits}
					placeholder="Enter your HTML code here..."
				/>
			</div>
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

<Modal
	bind:open={showCodeModal}
	on:close={() => (showCodeModal = false)}
	{preventEdits}
	bind:code
/>
