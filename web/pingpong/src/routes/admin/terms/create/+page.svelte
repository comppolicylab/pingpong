<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import SanitizeFlowbite from '$lib/components/SanitizeFlowbite.svelte';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import dayjs from 'dayjs';
  import { Button, ButtonGroup, Checkbox, Datepicker, Heading, Hr, Input, Label, Modal, P, Radio, Select, Textarea } from 'flowbite-svelte';
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
  let selectedValue = 1;
  let selectedColor = "";

  import MMMM from '$lib/components/CustomModal.svelte';
  let showModal = false;
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
    <form class="flex flex-col gap-4">
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
        <Datepicker disabled={$loading} color="blue"/>
      </div>
      <div>
        <Label for="always_display">Display</Label>
        <Checkbox
            id="always_display"
            name="always_display"
            disabled={$loading}
            >Require all every user to agree to this agreement.</Checkbox
          >
      </div>
      <div>
      <Label for="options">Options</Label>
      <div class="flex flex-col gap-4">
        <Radio name="example1" value="1" bind:group={selectedValue}>Display to all users</Radio>
        <Radio name="example1" value="2" bind:group={selectedValue}>Only display to users of certain providers</Radio>
      </div>  
      </div>
      <div>
        <Label for="description" class="mb-1">Description</Label>
        <Textarea name="description" id="description" bind:value={selectedColor} class="font-mono" disabled={$loading} />
      </div>
    </form>
    <Hr class="mt-8" />
    <div class="flex flex-row justify-end gap-4 mt-8">
      <ButtonGroup>
        <Button color="blue" type="submit">Create</Button>
        <Button color="light" type="button">Cancel</Button>
      </ButtonGroup>
    </div>
    <button on:click={() => (showModal = true)} class="bg-green-500 text-white p-2 rounded">
      Open Modal
    </button>
    <Hr class="mt-8" />
  <div>
<div class="flex flex-col w-full py-10 bg-blue-dark-50">
  <div class="flex items-center justify-center">
    <div class="flex flex-col w-11/12 lg:w-7/12 max-w-2xl rounded-4xl overflow-hidden">
      <header class="bg-blue-dark-40 px-12 py-8">
        <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
      </header>
      <div class="px-12 py-8 bg-white">
        <div class="flex flex-col gap-4">
          <SanitizeFlowbite html={selectedColor} />
          <div class="flex-row gap-4 text-center flex justify-end mt-4">
            <Button
              class="text-blue-dark-40 bg-white border border-blue-dark-40 rounded-full hover:bg-blue-dark-40 hover:text-white"
              type="button"
            >Exit PingPong</Button
            >
            <Button
              class="text-white bg-orange rounded-full hover:bg-orange-dark"
              >Accept</Button
            >
          </div>
        </div>
      </div>
    </div>
  </div>
</div>    
  </div>
  </div>
</div>



<MMMM isOpen={showModal} onClose={() => (showModal = false)}>
  <h2 class="text-xl font-bold">Modal Content</h2>
  <p>This is a customizable modal!</p>
</MMMM>