<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import dayjs from 'dayjs';
  import {
    Button,
    Checkbox,
    Datepicker,
    Heading,
    Helper,
    Hr,
    Input,
    Label,
    MultiSelect,
    Radio,
    Select,
    Textarea
  } from 'flowbite-svelte';
  import { ArrowRightOutline } from 'flowbite-svelte-icons';
  import { writable } from 'svelte/store';
  import Modal from '$lib/components/CustomModal.svelte';

  export let data;

  $: isCreating = data.isCreating;
  $: userAgreementToEdit = data.userAgreement;

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
    if (categoryId === 0) {
      const newCategory = d.newCategory?.toString();
      const showAll = d.newCategoryShowAll?.toString() === 'on';
      if (!newCategory) {
        $loading = false;
        return sadToast('Category is required');
      }
      const rawCategory = await api.createUserAgreementCategory(fetch, {
        name: newCategory,
        show_all: showAll
      });
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

    const params = {
      name,
      category_id: categoryId,
      effective_date: dayjs(effectiveDate).toISOString(),
      always_display: alwaysDisplay,
      apply_to_all: targetGroup === '1',
      code,
      limit_to_providers: $selectedProviders ? $selectedProviders : []
    };
    const rawAgreement = !userAgreementToEdit?.id
      ? await api.createUserAgreement(fetch, params)
      : await api.updateUserAgreement(fetch, userAgreementToEdit.id, params);
    const agreementResponse = api.expandResponse(rawAgreement);
    if (agreementResponse.error) {
      $loading = false;
      return sadToast(agreementResponse.error.detail || 'Unknown error saving agreement.');
    }
    happyToast('Agreement saved successfully!');
    await invalidateAll();
    await goto(`/admin/terms`);
    $loading = false;
  };

  let showCodeModal = false;

  $: categories = data.categories;
  $: externalProviders = data.externalProviders;
  $: availableProviders = externalProviders.map((provider) => ({
    value: provider.id,
    name: provider.name
  }));

  let selectedCategory: number | null = null;
  $: if (selectedCategory === null && userAgreementToEdit?.category?.id !== undefined) {
    selectedCategory = userAgreementToEdit.category.id;
  }
  let selectedTargetGroupValue = (data.userAgreement?.apply_to_all ?? true) ? '1' : '2';
  let code = '';
  $: if (userAgreementToEdit?.code && !code) {
    code = userAgreementToEdit.code;
  }
  let effectiveDate: Date | null = null;
  $: if (userAgreementToEdit?.effective_date && !effectiveDate) {
    effectiveDate = new Date(userAgreementToEdit.effective_date);
  }
  let selectedProviders = writable(
    data.userAgreement?.limit_to_providers.slice().map((provider) => provider.id)
  );
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
        >{isCreating ? 'Create' : 'Edit'} User Agreement</Heading
      >
    </div>
    <form class="flex flex-col gap-4" on:submit={handleSubmit}>
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
          value={userAgreementToEdit?.name}
          disabled={$loading}
        />
      </div>
      <div>
        <Label for="category" class="mb-1">Agreement Type</Label>
        <Helper class="mb-2"
          >Use Agreement Types to change how different user agreements may interact together.</Helper
        >
        <Select
          name="category"
          id="category"
          bind:value={selectedCategory}
          disabled={$loading}
          placeholder="Select an agreement type..."
        >
          {#each categories as category}
            <option value={category.id}>{category.name}</option>
          {/each}
          <option disabled>──────────</option>
          <option value={0}>+ Create new</option>
        </Select>
        {#if selectedCategory === 0}
          <div class="pt-4 flex flex-row gap-5">
            <div class="flex flex-col gap-2 w-1/3">
              <Label for="newCategory">Agreement Type Name</Label>
              <Input type="text" name="newCategory" id="newCategory" />
            </div>
            <div class="flex flex-col">
              <Label for="newCategoryShowAll" class="mb-1">Display Options</Label>
              <Helper class="mb-2"
                >By default, users will only be required to read and agree to the latest version of
                each agreement type.</Helper
              >
              <Checkbox id="newCategoryShowAll" name="newCategoryShowAll"
                >Require users to read and agree to every user agreement of this type.</Checkbox
              >
            </div>
          </div>
        {/if}
      </div>
      <div>
        <Label for="date" class="mb-1">Effective Date</Label>
        <Helper class="mb-2"
          >This date will be used to determine when the user agreement starts being displayed to
          users.</Helper
        >
        <Datepicker bind:value={effectiveDate} disabled={$loading} color="blue" />
      </div>
      <div>
        <Label for="always_display" class="mb-1">Display Options</Label>
        <Checkbox
          id="always_display"
          name="always_display"
          checked={userAgreementToEdit?.always_display}
          disabled={$loading}
          >Require every user to agree to this agreement, before displaying newer agreements of this
          agreement type.</Checkbox
        >
      </div>
      <div>
        <Label for="options" class="mb-1">Target Group</Label>
        <Helper class="mb-2"
          >Choose whether to show this agreement to all users or display to specific user groups.</Helper
        >
        <div class="flex flex-col gap-2">
          <Radio name="targetGroup" value="1" bind:group={selectedTargetGroupValue}
            >Display to all PingPong users.</Radio
          >
          <Radio name="targetGroup" value="2" bind:group={selectedTargetGroupValue}
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
            bind:value={$selectedProviders}
            items={availableProviders}
          />
        </div>
      {/if}
      <div>
        <div class="flex flex-row justify-between items-end mb-1">
          <Label for="code">Agreement Content</Label><Button
            pill
            size="sm"
            class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full py-0.5 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
            disabled={$loading}
            on:click={() => (showCodeModal = true)}
          >
            Edit with Preview
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
          disabled={$loading}
          placeholder="Enter your HTML code here..."
        />
      </div>
      <Hr class="mt-8" />
      <div class="flex flex-row justify-end gap-4">
        <Button
          disabled={$loading}
          href={`/admin/terms`}
          pill
          class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
          >Cancel</Button
        >
        <Button
          pill
          class="bg-orange border border-orange text-white hover:bg-orange-dark"
          type="submit"
          disabled={$loading}>Save</Button
        >
      </div>
    </form>
    <div></div>
  </div>
</div>

<Modal bind:open={showCodeModal} on:close={() => (showCodeModal = false)} bind:code />
