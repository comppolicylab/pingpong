<script lang="ts">
	import {
		Button,
		Heading,
		Modal,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell,
		Input,
		Label
	} from 'flowbite-svelte';
	import { ArrowRightOutline, PlusOutline, FileCopyOutline, PenSolid } from 'flowbite-svelte-icons';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import type { Institution } from '$lib/api';
	import * as api from '$lib/api';
	import { happyToast, sadToast } from '$lib/toast';
	import { resolve } from '$app/paths';
	import { ltiHeaderState } from '$lib/stores/ltiHeader';

	export let data;

	const sortInstitutions = (items: Institution[]) =>
		[...items].sort((a, b) => a.name.localeCompare(b.name));

	let institutions: Institution[] = sortInstitutions(data.institutions);
	let createModalOpen = false;
	let newInstitutionName = '';
	let creating = false;
	let copyModalOpen = false;
	let copyInstitutionId: number | null = null;
	let copyInstitutionName = '';
	let copying = false;

	$: isLtiHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	// Update props reactively when data changes
	$: if (isLtiHeaderLayout) {
		ltiHeaderState.set({
			kind: 'nongroup',
			props: {
				title: 'Admin',
				redirectUrl: '/admin',
				redirectName: 'Admin page'
			}
		});
	}

	const handleCreate = async () => {
		const trimmed = newInstitutionName.trim();
		if (!trimmed) {
			sadToast('Please enter an institution name.');
			return;
		}
		creating = true;
		const response = api.expandResponse(await api.createInstitution(fetch, { name: trimmed }));
		creating = false;
		if (response.error || !response.data) {
			sadToast(response.error?.detail || 'Unable to create institution.');
			return;
		}
		happyToast('Institution created');
		institutions = sortInstitutions([...institutions, response.data]);
		newInstitutionName = '';
		createModalOpen = false;
	};

	const openCopyModal = (inst: Institution) => {
		copyInstitutionId = inst.id;
		copyInstitutionName = `${inst.name} (Copy)`;
		copyModalOpen = true;
	};

	const handleCopy = async () => {
		if (!copyInstitutionId) return;
		const trimmed = copyInstitutionName.trim();
		if (!trimmed) {
			sadToast('Please enter a name for the copy.');
			return;
		}
		copying = true;
		const response = api.expandResponse(
			await api.copyInstitution(fetch, copyInstitutionId, { name: trimmed })
		);
		copying = false;
		if (response.error || !response.data) {
			sadToast(response.error?.detail || 'Unable to copy institution.');
			return;
		}
		happyToast('Institution copied');
		institutions = sortInstitutions([...institutions, response.data]);
		copyModalOpen = false;
		copyInstitutionId = null;
		copyInstitutionName = '';
	};
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !isLtiHeaderLayout}
		<PageHeader>
			<div slot="left">
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					Institutions
				</h2>
			</div>
			<div slot="right">
				<a
					href={resolve(`/admin`)}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>Admin page <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
		</PageHeader>
	{/if}

	<div class="h-full w-full overflow-y-auto p-12">
		<div class="mb-6 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>Manage Institutions</Heading
			>
			<Button
				pill
				size="sm"
				class="flex flex-row gap-2 border border-solid border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
				onclick={() => (createModalOpen = true)}><PlusOutline />New Institution</Button
			>
		</div>

		<div class="flex flex-col gap-4">
			<Table class="w-full">
				<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
					<TableHeadCell>Institution Name</TableHeadCell>
					<TableHeadCell></TableHeadCell>
				</TableHead>
				<TableBody>
					{#if institutions.length === 0}
						<TableBodyRow>
							<TableBodyCell colspan={2} class="py-4 text-sm text-gray-500">
								No institutions found.
							</TableBodyCell>
						</TableBodyRow>
					{/if}

					{#each institutions as institution (institution.id)}
						<TableBodyRow>
							<TableBodyCell class="py-2 font-medium whitespace-normal">
								{institution.name}
							</TableBodyCell>
							<TableBodyCell class="py-2 text-right">
								<div class="flex justify-end gap-2">
									<Button
										pill
										size="sm"
										class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
										href={`/admin/institutions/${institution.id}`}
									>
										<PenSolid size="sm" class="mr-1" />
										Edit
									</Button>
									<Button
										pill
										size="sm"
										class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
										onclick={() => openCopyModal(institution)}
									>
										<FileCopyOutline size="sm" class="mr-1" />
										Copy
									</Button>
								</div>
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
	</div>
</div>

<Modal bind:open={createModalOpen} size="md" onclose={() => (newInstitutionName = '')}>
	<div class="space-y-6 p-4">
		<Heading tag="h3" class="text-xl font-semibold text-gray-900">New Institution</Heading>
		<div class="flex flex-col gap-2">
			<Label for="institution-name" class="text-xs tracking-wide text-gray-600 uppercase"
				>Institution name</Label
			>
			<Input
				id="institution-name"
				name="institution-name"
				placeholder="Example University"
				bind:value={newInstitutionName}
			/>
		</div>
		<div class="flex justify-end gap-3">
			<Button color="light" onclick={() => (createModalOpen = false)}>Cancel</Button>
			<Button
				class="rounded-full bg-orange text-white hover:bg-orange-dark"
				disabled={creating || !newInstitutionName.trim()}
				onclick={handleCreate}
			>
				Create
			</Button>
		</div>
	</div>
</Modal>

<Modal bind:open={copyModalOpen} size="md" onclose={() => (copyInstitutionName = '')}>
	<div class="space-y-6 p-4">
		<Heading tag="h3" class="text-xl font-semibold text-gray-900">Copy Institution</Heading>
		<div class="flex flex-col gap-2">
			<Label for="copy-institution-name" class="text-xs tracking-wide text-gray-600 uppercase"
				>New name</Label
			>
			<Input
				id="copy-institution-name"
				name="copy-institution-name"
				placeholder="Institution name (Copy)"
				bind:value={copyInstitutionName}
			/>
		</div>
		<div class="flex justify-end gap-3">
			<Button color="light" onclick={() => (copyModalOpen = false)}>Cancel</Button>
			<Button
				class="rounded-full bg-orange text-white hover:bg-orange-dark"
				disabled={copying || !copyInstitutionName.trim()}
				onclick={handleCopy}
			>
				Copy
			</Button>
		</div>
	</div>
</Modal>
