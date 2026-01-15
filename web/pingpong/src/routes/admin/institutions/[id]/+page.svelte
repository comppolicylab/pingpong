<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import {
		Button,
		Heading,
		Helper,
		Input,
		Label,
		Select,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell
	} from 'flowbite-svelte';
	import { ArrowRightOutline, PlusOutline, TrashBinOutline } from 'flowbite-svelte-icons';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import * as api from '$lib/api';
	import { happyToast, sadToast } from '$lib/toast';
	import { loading } from '$lib/stores/general.js';
	import { resolve } from '$app/paths';

	let { data } = $props();
	
	const sortAdmins = (admins: api.InstitutionAdmin[]) =>
		[...admins].sort((a, b) =>
			(a.name || a.email || '').localeCompare(b.name || b.email || '', undefined, {
				sensitivity: 'base'
			})
		);


	const sortInstitutionAdmins = (inst: api.InstitutionWithAdmins) => ({
		...inst,
		admins: sortAdmins(inst.admins),
		root_admins: sortAdmins(inst.root_admins)
	});

	let institution: api.InstitutionWithAdmins = $derived(sortInstitutionAdmins(data.institution));
	let defaultKeys: api.DefaultAPIKey[] = $derived(data.defaultKeys || []);
	let draftName = $derived(institution.name);
	let newAdminEmail = $state('');
	let savingName = $state(false);
	let managingAdmins: Record<number, boolean> = $state({});
	let savingDefaultKey = $state(false);
	let selectedDefaultKeyId = $derived(institution.default_api_key_id
		? `${institution.default_api_key_id}`
		: '');

	let defaultKeyOptions = $derived([
		{ value: '', name: 'None' },
		...defaultKeys
			.slice()
			.sort((a, b) =>
				(a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' })
			)
			.map((key) => ({
				value: `${key.id}`,
				name: `${key.name || key.provider} (${key.redacted_key})`
			}))
	]);

	const refresh = async () => {
		const [institutionResponse, defaultKeysResponse] = await Promise.all([
			api.getInstitutionWithAdmins(fetch, institution.id).then(api.expandResponse),
			api.getDefaultAPIKeys(fetch).then(api.expandResponse)
		]);
		if (institutionResponse.error || !institutionResponse.data) {
			sadToast(institutionResponse.error?.detail || 'Unable to refresh institution');
			return;
		}
		if (defaultKeysResponse.error || !defaultKeysResponse.data) {
			sadToast(defaultKeysResponse.error?.detail || 'Unable to refresh default API keys');
			return;
		}
		institution = sortInstitutionAdmins(institutionResponse.data);
		defaultKeys = defaultKeysResponse.data.default_keys;
		draftName = institution.name;
		selectedDefaultKeyId = institution.default_api_key_id
			? `${institution.default_api_key_id}`
			: '';
		newAdminEmail = '';
		managingAdmins = {};
	};

	const saveName = async () => {
		const trimmed = draftName.trim();
		if (!trimmed || trimmed === institution.name) return;
		savingName = true;
		try {
			const response = api.expandResponse(
				await api.updateInstitution(fetch, institution.id, { name: trimmed })
			);
			if (response.error) {
				sadToast(response.error.detail || 'Could not update name');
				return;
			}
			happyToast('Institution renamed');
			await refresh();
			await invalidateAll();
		} catch (err) {
			console.error(err);
			sadToast('Could not update name');
		} finally {
			savingName = false;
		}
	};

	const addAdmin = async () => {
		const trimmed = newAdminEmail.trim();
		if (!trimmed) {
			sadToast('Enter an email address.');
			return;
		}
		managingAdmins[-1] = true;
		try {
			const response = api.expandResponse(
				await api.addInstitutionAdmin(fetch, institution.id, { email: trimmed })
			);
			if (response.error) {
				sadToast(response.error.detail || 'Could not add admin');
				return;
			}
			happyToast('Admin added');
			await refresh();
		} catch (err) {
			console.error(err);
			sadToast('Could not add admin');
		} finally {
			managingAdmins = { ...managingAdmins, [-1]: false };
		}
	};

	const removeAdmin = async (userId: number) => {
		managingAdmins = { ...managingAdmins, [userId]: true };
		try {
			const response = api.expandResponse(
				await api.removeInstitutionAdmin(fetch, institution.id, userId)
			);
			if (response.error) {
				sadToast(response.error.detail || 'Could not remove admin');
				return;
			}
			happyToast('Admin removed');
			await refresh();
		} catch (err) {
			console.error(err);
			sadToast('Could not remove admin');
		} finally {
			managingAdmins = { ...managingAdmins, [userId]: false };
		}
	};

	const saveDefaultApiKey = async () => {
		if ($loading || savingDefaultKey) return;
		savingDefaultKey = true;
		try {
			const keyId = selectedDefaultKeyId ? Number(selectedDefaultKeyId) : null;
			const response = api.expandResponse(
				await api.setInstitutionDefaultApiKey(fetch, institution.id, { default_api_key_id: keyId })
			);
			if (response.error) {
				sadToast(response.error.detail || 'Could not update default API key');
				return;
			}
			happyToast('Default API key updated');
			await refresh();
			await invalidateAll();
		} catch (err) {
			console.error(err);
			sadToast('Could not update default API key');
		} finally {
			savingDefaultKey = false;
		}
	};
</script>

<div class="relative flex h-full w-full flex-col">
	<PageHeader>
		{#snippet left()}
				<div >
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">Institutions</h2>
			</div>
			{/snippet}
		{#snippet right()}
				<div >
				<a
					href={resolve(`/admin/institutions`)}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>All Institutions <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
			{/snippet}
	</PageHeader>
	<div class="h-full w-full space-y-8 overflow-y-auto p-12">
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>Edit Institution</Heading
			>
		</div>
		<div>
			<Label for="name" class="mb-1">Institution Name</Label>
			<Helper class="mb-2"
				>This name will be used to identify institutions on the Admin page and Manage Group pages.</Helper
			>
			<Input
				type="text"
				name="name"
				id="name"
				placeholder="Institution name"
				bind:value={draftName}
				disabled={$loading || savingName}
				onchange={saveName}
			/>
		</div>
		<div>
			<Label for="default-api-key" class="mb-1">Default API Key</Label>
			<Helper class="mb-2">Optional: used for future defaults. Not currently used.</Helper>
			<Select
				id="default-api-key"
				name="default-api-key"
				items={defaultKeyOptions}
				bind:value={selectedDefaultKeyId}
				disabled={$loading || savingDefaultKey}
				onchange={saveDefaultApiKey}
			/>
		</div>
		<div class="space-y-4">
			<Heading tag="h4" class="text-dark-blue-40 font-serif text-xl font-medium">
				Institutional Admins
			</Heading>
			<Table class="w-full">
				<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
					<TableHeadCell>Name</TableHeadCell>
					<TableHeadCell>Email</TableHeadCell>
					<TableHeadCell></TableHeadCell>
				</TableHead>
				<TableBody>
					{#if institution.admins.length === 0}
						<TableBodyRow>
							<TableBodyCell colspan={3} class="py-3 text-sm text-gray-500">
								No institutional admins yet.
							</TableBodyCell>
						</TableBodyRow>
					{/if}
					{#each institution.admins as admin (admin.id)}
						<TableBodyRow>
							<TableBodyCell class="py-2 font-medium whitespace-normal">
								{admin.name || 'Unknown'}
							</TableBodyCell>
							<TableBodyCell class="py-2 font-normal whitespace-normal">
								{admin.email || 'N/A'}
							</TableBodyCell>
							<TableBodyCell class="py-2">
								<Button
									pill
									size="sm"
									class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-red-200 bg-white p-1 px-3 text-xs text-red-700 transition-all hover:bg-red-600 hover:text-white"
									disabled={!!managingAdmins[admin.id]}
									onclick={() => removeAdmin(admin.id)}
								>
									<TrashBinOutline size="sm" class="mr-1" />
									Remove
								</Button>
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>

			<div class="flex max-w-3xl flex-col gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4">
				<Label class="text-xs tracking-wide text-blue-900 uppercase">Add admin by email</Label>
				<div class="flex flex-row gap-3">
					<Input
						type="email"
						placeholder="admin@example.edu"
						class="sm:flex-1"
						bind:value={newAdminEmail}
						name="admin-email"
					/>
					<Button
						onclick={addAdmin}
						disabled={!!managingAdmins[-1] || !newAdminEmail.trim()}
						class="rounded-full bg-blue-dark-40 px-3 text-white hover:bg-blue-dark-50"
					>
						<PlusOutline class="mr-2" />
						Add admin
					</Button>
				</div>
			</div>
		</div>

		<div class="space-y-3">
			<Heading tag="h4" class="text-dark-blue-40 font-serif text-xl font-medium">
				Root Admins (inherited)
			</Heading>
			<Table class="w-full">
				<TableHead class="rounded-2xl bg-gray-100 p-1 tracking-wide text-gray-700">
					<TableHeadCell>Name</TableHeadCell>
					<TableHeadCell>Email</TableHeadCell>
				</TableHead>
				<TableBody>
					{#if institution.root_admins.length === 0}
						<TableBodyRow>
							<TableBodyCell colspan={2} class="py-3 text-sm text-gray-500">
								No root admins configured.
							</TableBodyCell>
						</TableBodyRow>
					{/if}
					{#each institution.root_admins as admin (admin.id)}
						<TableBodyRow>
							<TableBodyCell class="py-2 font-medium whitespace-normal">
								{admin.name || 'Unknown'}
							</TableBodyCell>
							<TableBodyCell class="py-2 font-normal whitespace-normal">
								{admin.email || 'N/A'}
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
	</div>
</div>
