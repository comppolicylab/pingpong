<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { resolve } from '$app/paths';
	import * as api from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { happyToast, sadToast } from '$lib/toast';
	import { Button, Heading, Input, Label, Modal, P, Textarea } from 'flowbite-svelte';
	import { ArrowRightOutline } from 'flowbite-svelte-icons';
	import { ltiHeaderComponent, ltiHeaderProps } from '$lib/stores/ltiHeader';
	import NonGroupHeader from '$lib/components/NonGroupHeader.svelte';

	export let data;
	$: externalProviders = data.externalProviders;

	$: isLtiHeaderLayout = data.forceCollapsedLayout && data.forceShowSidebarButton;

	// Update props reactively when data changes
	$: if (isLtiHeaderLayout) {
		ltiHeaderComponent.set(NonGroupHeader);
		ltiHeaderProps.set({
			title: 'External Login Providers',
			redirectUrl: '/admin',
			redirectName: 'Admin page'
		});
	}

	let editModalOpen = false;
	let providerToEdit: api.ExternalLoginProvider | null = null;
	const openEditModal = (provider_id: number) => {
		providerToEdit = externalProviders.find((provider) => provider.id === provider_id) || null;
		if (!providerToEdit) {
			sadToast('Could not find provider to edit.');
			return;
		}
		editModalOpen = true;
	};

	const handleSubmit = async (event: Event) => {
		event.preventDefault();
		if (!providerToEdit) return;

		const formData = new FormData(event.target as HTMLFormElement);
		const updatedProvider = {
			display_name: formData.get('display_name') as string,
			description: formData.get('description') as string
		};

		const result = await api.updateExternalLoginProvider(fetch, providerToEdit.id, updatedProvider);
		const response = api.expandResponse(result);
		if (response.error) {
			sadToast(response.error.detail || 'An unknown error occurred');
		} else {
			happyToast(`Provider updated successfully.`);
			providerToEdit = null;
			invalidateAll();
			editModalOpen = false;
		}
	};
</script>

<div class="relative flex h-full w-full flex-col">
	{#if !isLtiHeaderLayout}
		<PageHeader>
			<div slot="left">
				<h2 class="text-color-blue-dark-50 px-4 py-3 font-serif text-3xl font-bold">
					External Login Providers
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
		<div class="mb-4 flex flex-row flex-wrap items-center justify-between gap-y-4">
			<Heading
				tag="h2"
				class="text-dark-blue-40 mr-5 max-w-max shrink-0 font-serif text-3xl font-medium"
				>Manage External Login Providers</Heading
			>
		</div>
		<div class="flex flex-col gap-4">
			<P>
				PingPong supports log in and user syncing functionality with a number of External Login
				Providers. Configure how External Login Providers appear to your users. You can customize
				the display name, icon, and description for each provider.
			</P>
			<div class="rounded-2xl bg-gray-100 p-6">
				<div class="grid grid-cols-1 gap-4">
					{#each externalProviders as provider (provider.id)}
						<div class="rounded-xl bg-white p-4 shadow-xs">
							<div class="flex flex-wrap items-center justify-between gap-4">
								<div class="flex flex-1 items-center gap-4">
									<div class="flex w-1/4 shrink-0 items-center gap-4">
										<div class="flex flex-col">
											<span class="text-lg font-medium"
												>{provider.display_name || provider.name}</span
											>
											<span class="font-mono text-sm text-gray-600">{provider.name}</span>
										</div>
									</div>
									{#if provider.description}
										<p class="max-w-xl text-sm text-gray-600">{provider.description}</p>
									{:else}
										<p class="text-sm text-gray-400 italic">No description set</p>
									{/if}
								</div>
								<Button
									pill
									size="sm"
									class="flex shrink-0 flex-row items-center justify-center gap-1.5 rounded-full border border-blue-dark-40 bg-white p-1 px-3 text-xs text-blue-dark-40 transition-all hover:bg-blue-dark-40 hover:text-white"
									onclick={() => openEditModal(provider.id)}
								>
									Edit
								</Button>
							</div>
						</div>
					{/each}
				</div>
			</div>
		</div>
	</div>
</div>

<Modal bind:open={editModalOpen} size="sm" onclose={() => (providerToEdit = null)}>
	<form class="flex flex-col space-y-6 pb-4" action="#" onsubmit={handleSubmit}>
		<h3 class="mb-2 text-xl font-medium text-gray-900 dark:text-white">
			Editing properties for <span class="font-mono">{providerToEdit?.name}</span>
		</h3>
		<Label class="space-y-2">
			<span>Display Name</span>
			<Input
				type="text"
				id="display_name"
				name="display_name"
				placeholder="Acme SSO"
				value={providerToEdit?.display_name}
			/>
		</Label>
		<Label class="space-y-2">
			<span>Description</span>
			<Textarea
				id="description"
				name="description"
				placeholder="Your SSO identifier when logging in through Acme..."
				rows={3}
				value={providerToEdit?.description ?? ''}
			/>
		</Label>
		<div class="flex justify-center">
			<Button type="submit" class="w-fit rounded-full bg-orange-dark text-white hover:bg-orange"
				>Save</Button
			>
		</div>
	</form>
</Modal>
