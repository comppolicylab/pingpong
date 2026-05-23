<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import DropdownBadge from '$lib/components/DropdownBadge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { happyToast, sadToast } from '$lib/toast';
	import {
		Badge,
		Button,
		Heading,
		Input,
		Label,
		Modal,
		P,
		Select,
		Table,
		TableBody,
		TableBodyCell,
		TableBodyRow,
		TableHead,
		TableHeadCell,
		Toggle
	} from 'flowbite-svelte';
	import { ArrowRightOutline, PenSolid, PlusOutline } from 'flowbite-svelte-icons';
	import { headerState } from '$lib/stores/header';

	export let data;
	$: connectorConfigs = data.connectorConfigs;
	$: connectorServices = data.connectorServices;

	$: isNewHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	$: if (isNewHeaderLayout) {
		headerState.set({
			kind: 'nongroup',
			props: {
				title: 'Connectors',
				redirectUrl: '/admin',
				redirectName: 'Admin page'
			}
		});
	}

	const serviceDisplayName = (slug: string) => {
		const svc = connectorServices.find((s) => s.slug === slug);
		return svc ? svc.display_name : slug;
	};

	const formatDate = (dateStr: string) => {
		return new Date(dateStr).toLocaleDateString('en-US', {
			year: 'numeric',
			month: 'short',
			day: 'numeric'
		});
	};

	let createModalOpen = false;
	let createForm = {
		service: '',
		account_scope: '',
		display_name: '',
		host: '',
		client_id: '',
		client_secret: '',
		enabled: true
	};
	let creating = false;

	const openCreateModal = () => {
		createForm = {
			service: connectorServices[0]?.slug ?? '',
			account_scope: '',
			display_name: '',
			host: '',
			client_id: '',
			client_secret: '',
			enabled: true
		};
		createModalOpen = true;
	};

	const handleCreate = async (event: Event) => {
		event.preventDefault();
		if (creating) return;
		if (!createForm.service) {
			sadToast('Please select a service.');
			return;
		}
		creating = true;
		const result = await api.createConnectorConfig(fetch, { ...createForm });
		const response = api.expandResponse(result);
		creating = false;
		if (response.error) {
			sadToast(response.error.detail || 'Failed to create connector.');
			return;
		}
		happyToast('Connector created.');
		createModalOpen = false;
		invalidateAll();
	};

	let editModalOpen = false;
	let configToEdit: api.ConnectorConfig | null = null;
	let editForm = {
		display_name: '',
		host: '',
		client_id: '',
		client_secret: '',
		enabled: true
	};
	let editing = false;

	const openEditModal = (config: api.ConnectorConfig) => {
		configToEdit = config;
		editForm = {
			display_name: config.display_name,
			host: config.host,
			client_id: config.client_id,
			client_secret: '',
			enabled: config.enabled
		};
		editModalOpen = true;
	};

	const handleEdit = async (event: Event) => {
		event.preventDefault();
		if (editing || !configToEdit) return;
		editing = true;
		const result = await api.updateConnectorConfig(fetch, configToEdit.id, {
			display_name: editForm.display_name,
			host: editForm.host,
			client_id: editForm.client_id,
			client_secret: editForm.client_secret ? editForm.client_secret : null,
			enabled: editForm.enabled
		});
		const response = api.expandResponse(result);
		editing = false;
		if (response.error) {
			sadToast(response.error.detail || 'Failed to update connector.');
			return;
		}
		happyToast('Connector updated.');
		editModalOpen = false;
		configToEdit = null;
		invalidateAll();
	};

	$: serviceOptions = connectorServices.map((s) => ({ value: s.slug, name: s.display_name }));
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !isNewHeaderLayout}
		<PageHeader>
			<div slot="left">
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">Connectors</h2>
			</div>
			<div slot="right">
				<a
					href={resolve('/admin')}
					class="flex items-center gap-2 rounded-full bg-white p-2 px-4 text-sm font-medium text-blue-dark-50 transition-all hover:bg-blue-dark-40 hover:text-white"
					>Admin page <ArrowRightOutline size="md" class="text-orange" /></a
				>
			</div>
		</PageHeader>
	{/if}

	<div class="w-full p-12 pt-6">
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<div class="mr-5 flex flex-wrap items-center gap-3">
				<Heading
					tag="h2"
					class="text-dark-blue-40 max-w-max shrink-0 font-serif text-3xl font-medium"
					>Manage Connectors</Heading
				>
				<DropdownBadge>
					<span slot="name" class="uppercase">Under Development</span>
				</DropdownBadge>
			</div>
			<Button
				class="flex items-center gap-2 rounded-full bg-orange text-white hover:bg-orange-dark"
				disabled={connectorServices.length === 0}
				onclick={openCreateModal}
			>
				<PlusOutline size="sm" />
				Add Connector
			</Button>
		</div>

		<div class="flex flex-col gap-4">
			<P>Configure connectors that let users link their accounts to external services.</P>

			<Table class="w-full">
				<TableHead class="rounded-2xl bg-blue-light-40 p-1 tracking-wide text-blue-dark-50">
					<TableHeadCell>Service</TableHeadCell>
					<TableHeadCell>Display name</TableHeadCell>
					<TableHeadCell>Tenant</TableHeadCell>
					<TableHeadCell>Host</TableHeadCell>
					<TableHeadCell>Client ID</TableHeadCell>
					<TableHeadCell>Enabled</TableHeadCell>
					<TableHeadCell>Created</TableHeadCell>
					<TableHeadCell></TableHeadCell>
				</TableHead>
				<TableBody>
					{#if connectorConfigs.length === 0}
						<TableBodyRow>
							<TableBodyCell colspan={8} class="py-4 text-sm text-gray-500">
								No connectors configured yet.
							</TableBodyCell>
						</TableBodyRow>
					{/if}

					{#each connectorConfigs as config (config.id)}
						<TableBodyRow>
							<TableBodyCell class="py-2">
								<div class="flex flex-col">
									<span class="font-medium">{serviceDisplayName(config.service)}</span>
									<span class="font-mono text-xs text-gray-500">{config.service}</span>
								</div>
							</TableBodyCell>
							<TableBodyCell class="py-2 whitespace-normal">{config.display_name}</TableBodyCell>
							<TableBodyCell class="py-2 font-mono text-xs">{config.account_scope}</TableBodyCell>
							<TableBodyCell class="max-w-xs py-2 break-all whitespace-normal">
								{config.host}
							</TableBodyCell>
							<TableBodyCell class="max-w-xs py-2 font-mono text-xs break-all whitespace-normal">
								{config.client_id}
							</TableBodyCell>
							<TableBodyCell class="py-2">
								{#if config.enabled}
									<Badge color="green">Enabled</Badge>
								{:else}
									<Badge color="dark">Disabled</Badge>
								{/if}
							</TableBodyCell>
							<TableBodyCell class="py-2 text-sm text-gray-600">
								{formatDate(config.created)}
							</TableBodyCell>
							<TableBodyCell class="py-2 text-right">
								<Button
									pill
									size="sm"
									class="flex w-fit shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
									onclick={() => openEditModal(config)}
								>
									<PenSolid size="sm" class="mr-1" />
									Edit
								</Button>
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
	</div>
</div>

<Modal bind:open={createModalOpen} size="md" onclose={() => (createModalOpen = false)}>
	<div class="space-y-6 p-4">
		<Heading tag="h3" class="text-xl font-semibold text-gray-900">Add Connector</Heading>

		<div class="flex flex-col gap-2">
			<Label for="connector-service" class="text-xs tracking-wide text-gray-600 uppercase"
				>Service</Label
			>
			<Select id="connector-service" items={serviceOptions} bind:value={createForm.service} />
		</div>

		<div class="flex flex-col gap-2">
			<Label for="connector-display-name" class="text-xs tracking-wide text-gray-600 uppercase"
				>Display name</Label
			>
			<Input
				id="connector-display-name"
				placeholder="University of Example"
				bind:value={createForm.display_name}
			/>
		</div>

		<div class="flex flex-col gap-2">
			<Label for="connector-tenant" class="text-xs tracking-wide text-gray-600 uppercase"
				>Tenant</Label
			>
			<Input
				id="connector-tenant"
				placeholder="example-tenant"
				bind:value={createForm.account_scope}
			/>
		</div>

		<div class="flex flex-col gap-2">
			<Label for="connector-host" class="text-xs tracking-wide text-gray-600 uppercase">Host</Label>
			<Input
				id="connector-host"
				placeholder="example.hosted.service.com"
				bind:value={createForm.host}
			/>
		</div>

		<div class="flex flex-col gap-2">
			<Label for="connector-client-id" class="text-xs tracking-wide text-gray-600 uppercase"
				>Client ID</Label
			>
			<Input id="connector-client-id" autocomplete="off" bind:value={createForm.client_id} />
		</div>

		<div class="flex flex-col gap-2">
			<Label for="connector-client-secret" class="text-xs tracking-wide text-gray-600 uppercase"
				>Client secret</Label
			>
			<Input
				id="connector-client-secret"
				type="password"
				autocomplete="new-password"
				bind:value={createForm.client_secret}
			/>
		</div>

		<div class="flex items-center gap-3">
			<Toggle bind:checked={createForm.enabled} color="blue" />
			<span class="text-sm">Enabled</span>
		</div>

		<div class="flex justify-end gap-3">
			<Button color="light" onclick={() => (createModalOpen = false)}>Cancel</Button>
			<Button
				class="rounded-full bg-orange text-white hover:bg-orange-dark"
				disabled={creating ||
					!createForm.service ||
					!createForm.display_name.trim() ||
					!createForm.account_scope.trim() ||
					!createForm.host.trim() ||
					!createForm.client_id.trim() ||
					!createForm.client_secret.trim()}
				onclick={handleCreate}
			>
				{creating ? 'Creating…' : 'Create'}
			</Button>
		</div>
	</div>
</Modal>

<Modal bind:open={editModalOpen} size="md" onclose={() => (configToEdit = null)}>
	<div class="space-y-6 p-4">
		<Heading tag="h3" class="text-xl font-semibold text-gray-900">
			Edit <span class="font-mono">{configToEdit?.service}</span> /
			<span class="font-mono">{configToEdit?.account_scope}</span>
		</Heading>

		<div class="flex flex-col gap-2">
			<Label for="edit-connector-display-name" class="text-xs tracking-wide text-gray-600 uppercase"
				>Display name</Label
			>
			<Input id="edit-connector-display-name" bind:value={editForm.display_name} />
		</div>

		<div class="flex flex-col gap-2">
			<Label for="edit-connector-host" class="text-xs tracking-wide text-gray-600 uppercase"
				>Host</Label
			>
			<Input id="edit-connector-host" bind:value={editForm.host} />
		</div>

		<div class="flex flex-col gap-2">
			<Label for="edit-connector-client-id" class="text-xs tracking-wide text-gray-600 uppercase"
				>Client ID</Label
			>
			<Input id="edit-connector-client-id" bind:value={editForm.client_id} />
		</div>

		<div class="flex flex-col gap-2">
			<Label
				for="edit-connector-client-secret"
				class="text-xs tracking-wide text-gray-600 uppercase">Client secret</Label
			>
			<Input
				id="edit-connector-client-secret"
				type="password"
				placeholder="Leave blank to keep current secret"
				bind:value={editForm.client_secret}
			/>
		</div>

		<div class="flex items-center gap-3">
			<Toggle bind:checked={editForm.enabled} color="blue" />
			<span class="text-sm">Enabled</span>
		</div>

		<div class="flex justify-end gap-3">
			<Button color="light" onclick={() => (editModalOpen = false)}>Cancel</Button>
			<Button
				class="rounded-full bg-orange text-white hover:bg-orange-dark"
				disabled={editing ||
					!editForm.display_name.trim() ||
					!editForm.host.trim() ||
					!editForm.client_id.trim()}
				onclick={handleEdit}
			>
				{editing ? 'Saving…' : 'Save'}
			</Button>
		</div>
	</div>
</Modal>
