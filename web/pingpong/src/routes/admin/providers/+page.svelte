<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { happyToast, sadToast } from '$lib/toast';
  import { Button, Heading, Input, Label, Modal, P, Textarea } from 'flowbite-svelte';
  import { ArrowRightOutline } from 'flowbite-svelte-icons';
  export let data;
  $: externalProviders = data.externalProviders;

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

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">
        External Login Providers
      </h2>
    </div>
    <div slot="right">
      <a
        href={`/admin`}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-blue-dark-40 transition-all flex items-center gap-2"
        >Admin page <ArrowRightOutline size="md" class="text-orange" /></a
      >
    </div>
  </PageHeader>
  <div class="h-full w-full overflow-y-auto p-12">
    <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >Manage External Login Providers</Heading
      >
    </div>
    <div class="flex flex-col gap-4">
      <P>
        PingPong supports log in and user syncing functionality with a number of External Login
        Providers. Configure how External Login Providers appear to your users. You can customize
        the display name, icon, and description for each provider.
      </P>
      <div class="bg-gray-100 rounded-2xl p-6">
        <div class="grid grid-cols-1 gap-4">
          {#each externalProviders as provider}
            <div class="bg-white rounded-xl p-4 shadow-sm">
              <div class="flex items-center justify-between flex-wrap gap-4">
                <div class="flex items-center gap-4 flex-1">
                  <div class="flex items-center gap-4 w-1/4 shrink-0">
                    <div class="flex flex-col">
                      <span class="font-medium text-lg"
                        >{provider.display_name || provider.name}</span
                      >
                      <span class="text-sm text-gray-600 font-mono">{provider.name}</span>
                    </div>
                  </div>
                  {#if provider.description}
                    <p class="text-gray-600 text-sm max-w-xl">{provider.description}</p>
                  {:else}
                    <p class="text-gray-400 text-sm italic">No description set</p>
                  {/if}
                </div>
                <Button
                  pill
                  size="sm"
                  class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all"
                  on:click={() => openEditModal(provider.id)}
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

<Modal bind:open={editModalOpen} size="sm" on:close={() => (providerToEdit = null)}>
  <form class="flex flex-col space-y-6 pb-4" action="#" on:submit={handleSubmit}>
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
      <Button type="submit" class="bg-orange-dark text-white rounded-full hover:bg-orange w-fit"
        >Save</Button
      >
    </div>
  </form>
</Modal>
