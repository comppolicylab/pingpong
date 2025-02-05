<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import dayjs from 'dayjs';
  import { Button, ButtonGroup, Checkbox, Datepicker, Heading, Input, Label, Modal, P, Radio, Select, Textarea } from 'flowbite-svelte';
  import { ArrowRightOutline, PlusOutline } from 'flowbite-svelte-icons';
  import { onMount } from 'svelte';
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
  let institutions: api.Institution[] = [
    { id: 1, name: 'Institution 1', description: null, created: '2022-01-01T00:00:00Z', updated: '2022-01-01T00:00:00Z', logo: null },
    { id: 2, name: 'Institution 2', description: null, created: '2022-01-01T00:00:00Z', updated: '2022-01-01T00:00:00Z', logo: null },
    { id: 3, name: 'Institution 3', description: null, created: '2022-01-01T00:00:00Z', updated: '2022-01-01T00:00:00Z', logo: null },
    { id: 4, name: 'Institution 4', description: null, created: '2022-01-01T00:00:00Z', updated: '2022-01-01T00:00:00Z', logo: null },
    { id: 5, name: 'Institution 5', description: null, created: '2022-01-01T00:00:00Z', updated: '2022-01-01T00:00:00Z', logo: null }
  ];
  let selectedInst = '';
  let colors = "text-purple-500";
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">
        User Agreements
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
        >Create User Agreement</Heading
      >
    </div>
    <form class="flex flex-col gap-4 max-w-lg sm:min-w-[32rem]">
      <div>
        <Label for="name" class="mb-1">Agreement Name</Label>
        <Input type="text" name="name" id="name" disabled={$loading} />
      </div>
      <div>
        <Label for="category" class="mb-1">Agreement Type</Label>
        <Select name="institution" id="institution" bind:value={selectedInst} disabled={$loading}>
          {#each institutions as inst}
            <option value={inst.id}>{inst.name}</option>
          {/each}
            <option disabled>──────────</option>
            <option value="0">+ Create new</option>
        </Select>
        {#if selectedInst === '0'}
          <div class="pt-4">
            <Label for="newInstitution">New Type</Label>
            <Input type="text" name="newInstitution" id="new-inst" />
          </div>
        {/if}
      </div>
      <div>
        <Label for="date">Effective Date</Label>
        <Datepicker id="date" disabled={$loading} color="blue"/>
      </div>
      <div>
        <Label for="date">Effective Date</Label>
        <Checkbox
            id="always_display"
            name="always_display"
            disabled={$loading}
            >Require all every user to agree to this agreement.</Checkbox
          >
      </div>
      <div>
      <Label for="options">Options</Label>
      <div class="flex gap-4 *:! ring-blue-700">
        <Radio color="blue" id="option1" name="options" value="1" disabled={$loading} />
        <Label for="option1">Option 1</Label>
        <Radio color="blue" id="option2" name="options" value="2" disabled={$loading} />
        <Label for="option2">Option 2</Label>
      </div>
      </div>
    </form>
  </div>
</div>