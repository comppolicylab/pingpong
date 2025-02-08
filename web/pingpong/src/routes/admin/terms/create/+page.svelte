<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import SanitizeFlowbite from '$lib/components/SanitizeFlowbite.svelte';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import dayjs from 'dayjs';
  import { Button, ButtonGroup, Checkbox, Datepicker, Heading, Helper, Hr, Input, Label, Modal, P, Radio, Select, Textarea } from 'flowbite-svelte';
  import { ArrowRightOutline, PlusOutline } from 'flowbite-svelte-icons';
  import { onMount } from 'svelte';
  export let data;

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
    $loading = true;

    const form = event.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const name = d.name?.toString();
    if (!name) {
      $loading = false;
      return sadToast('Name is required');
    }

    let categoryId = parseInt(d.category?.toString(), 10);
    if (!categoryId) {
      const newCategory = d.newCategory?.toString();
      const showAll = d.newCategoryShowAll?.toString() === 'on';
      if (!newCategory) {
        $loading = false;
        return sadToast('Category is required');
      }
      const rawCategory = await api.createUserAgreementCategory(fetch, { name: newCategory, show_all: showAll });
      const categoryResponse = api.expandResponse(rawCategory);
      if (categoryResponse.error) {
        $loading = false;
        return sadToast(categoryResponse.error.detail || 'Unknown error creating category');
      }
      categoryId = categoryResponse.data.id;

      if (!categoryId) {
        $loading = false;
        return sadToast('Category is required');
      }
    }

    if (!effectiveDate) {
      $loading = false;
      return sadToast('Date is required');
    }

    const alwaysDisplay = d.always_display?.toString() === 'on';
    const targetGroup = d.targetGroup?.toString();
    const code = d.code?.toString();
    
    const rawAgreement = await api.createUserAgreement(fetch, {
      name,
      category_id: categoryId,
      effective_date: dayjs(effectiveDate).toISOString(),
      always_display: alwaysDisplay,
      apply_to_all: targetGroup === '1',
      code,
      limit_to_providers: [],
    });
    const agreementResponse = api.expandResponse(rawAgreement);
    if (agreementResponse.error) {
      $loading = false;
      return sadToast(agreementResponse.error.detail || 'Unknown error creating agreement');
    }
    $loading = false;
    happyToast('Agreement created');
    await invalidateAll();
    form.reset();
    await goto(`/admin/terms`);
  };

  import MMMM from '$lib/components/CustomModal.svelte';
  let showModal = false;

  $: categories = data.categories;
  $: externalProviders = data.externalProviders;

  let selectedCategory = '';
  let selectedTargetGroupValue = '1';
  let code = '';
  let effectiveDate: Date | null = null;
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
    <form class="flex flex-col gap-4" on:submit={handleSubmit}>
      <div>
        <Label for="name" class="mb-1">Agreement Name</Label>
        <Helper class="mb-2">This name will be used to identify user agreements on the Admin Page and will not be displayed to users.</Helper>
        <Input type="text" name="name" id="name" disabled={$loading} />
      </div>
      <div>
        <Label for="category" class="mb-1">Agreement Type</Label>
        <Helper class="mb-2">Use Agreement Types to change how different user agreements may interact together.</Helper>
        <Select name="category" id="category" bind:value={selectedCategory} disabled={$loading} placeholder="Select an agreement type...">
          {#each categories as inst}
            <option value={inst.id}>{inst.name}</option>
          {/each}
            <option disabled>──────────</option>
            <option value="0">+ Create new</option>
        </Select>
        {#if selectedCategory === '0'}
          <div class="pt-4 flex flex-row gap-5">
            <div class="flex flex-col gap-2 w-1/3">
              <Label for="newCategory">Agreement Type Name</Label>
              <Input type="text" name="newCategory" id="newCategory" />
            </div>
            <div class="flex flex-col">
              <Label for="newCategoryShowAll" class="mb-1">Display Options</Label>
              <Helper class="mb-2">By default, users will only be required to read and agree to the latest version of each agreement type.</Helper>
              <Checkbox
                id="newCategoryShowAll"
                name="newCategoryShowAll"
                >Require users to read and agree to every user agreement of this type.</Checkbox
              >
            </div>
          </div>
        {/if}
      </div>
      <div>
        <Label for="date" class="mb-1">Effective Date</Label>
        <Helper class="mb-2">This date will be used to determine when the user agreement starts being displayed to users.</Helper>
        <Datepicker bind:value={effectiveDate} disabled={$loading} color="blue"/>
      </div>
      <div>
        <Label for="always_display" class="mb-1">Display Options</Label>
        <Checkbox
            id="always_display"
            name="always_display"
            disabled={$loading}
            >Require every user to agree to this agreement, even if they are newer agreements in this agreement type.</Checkbox
          >
      </div>
      <div>
      <Label for="options" class="mb-1">Target Group</Label>
      <Helper class="mb-2">Choose whether to show this agreement to all users or display to specific user groups.</Helper>
      <div class="flex flex-col gap-2">
        <Radio name="targetGroup" value="1" bind:group={selectedTargetGroupValue}>Display to all PingPong users.</Radio>
        <Radio name="targetGroup" value="2" bind:group={selectedTargetGroupValue}>Only display to users of specific External Login Providers.</Radio>
      </div>
      </div>
      <div>
        <Label for="code" class="mb-1">Code</Label>
        <Textarea name="code" id="code" bind:value={code} class="font-mono" disabled={$loading} />
      </div>
      <Hr class="mt-8" />
      <div class="flex flex-row justify-end gap-4 mt-8">
        <ButtonGroup>
          <Button color="blue" type="submit">Create</Button>
          <Button color="light" type="button">Cancel</Button>
        </ButtonGroup>
      </div>  
    </form>
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
          <SanitizeFlowbite html={code} />
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
