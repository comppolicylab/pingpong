<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import { resolve } from '$app/paths';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import {
    Button,
    Heading,
    Helper,
    Hr,
    Input,
    Label,
    MultiSelect,
    Radio,
    Select
  } from 'flowbite-svelte';
  import { ArrowRightOutline, LockSolid } from 'flowbite-svelte-icons';
  import { writable } from 'svelte/store';

  export let data;

  $: isCreating = data.isCreating;
  $: agreementPolicyToEdit = data.agreementPolicy;
  $: agreements = data.agreements;
  $: availableAgreements = agreements.map((agreement) => ({
    value: agreement.id,
    name: agreement.name
  }));
  $: externalProviders = data.externalProviders;
  $: availableProviders = externalProviders.map((provider) => ({
    value: provider.id,
    name: provider.name
  }));

  const handleSubmit = async (event: Event) => {
    event.preventDefault();
    $loading = true;

    const form = event.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const name = d.name?.toString();

    if (!name) {
      $loading = false;
      return sadToast('Please enter a name for the agreement policy.');
    }

    if (!selectedAgreement) {
      $loading = false;
      return sadToast('Please select an agreement.');
    }

    if (selectedTargetGroupValue === '2' && $selectedProviders.length === 0) {
      $loading = false;
      return sadToast('Please select at least one external login provider.');
    }

    const params = {
      name,
      agreement_id: selectedAgreement,
      apply_to_all: selectedTargetGroupValue === '1',
      limit_to_providers: selectedTargetGroupValue === '2' ? $selectedProviders : null
    };
    const rawAgreement = !agreementPolicyToEdit?.id
      ? await api.createAgreementPolicy(fetch, params)
      : await api.updateAgreementPolicy(fetch, agreementPolicyToEdit.id, params);
    const agreementResponse = api.expandResponse(rawAgreement);
    if (agreementResponse.error) {
      $loading = false;
      return sadToast(agreementResponse.error.detail || 'Unknown error saving agreement policy.');
    }
    happyToast('Agreement policy saved successfully!');
    await invalidateAll();
    await goto(resolve(`/admin/terms`));
    $loading = false;
  };

  let selectedAgreement: number | null = null;
  $: if (selectedAgreement === null && agreementPolicyToEdit?.agreement_id !== undefined) {
    selectedAgreement = agreementPolicyToEdit?.agreement_id;
  }

  let selectedTargetGroupValue = (data.agreementPolicy?.apply_to_all ?? true) ? '1' : '2';
  let selectedProviders = writable(
    data.agreementPolicy?.limit_to_providers.slice().map((provider) => provider.id)
  );

  $: preventEdits = !!agreementPolicyToEdit?.not_before || false;
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">
        Agreement Policies
      </h2>
    </div>
    <div slot="right">
      <a
        href={resolve(`/admin/terms`)}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-blue-dark-40 transition-all flex items-center gap-2"
        >All Agreements <ArrowRightOutline size="md" class="text-orange" /></a
      >
    </div>
  </PageHeader>
  <div class="h-full w-full overflow-y-auto p-12">
    <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >{isCreating ? 'Create' : 'Edit'} Agreement Policy</Heading
      >
    </div>
    {#if preventEdits}
      <div
        class="flex col-span-2 items-center rounded-lg text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 p-4 mb-4"
      >
        <LockSolid class="w-8 h-8 mr-3" />
        <div class="flex flex-row justify-between items-center gap-5 w-full">
          <span>
            This Agreement Policy has already been enabled and cannot be edited.<br />To make
            changes, create a new Policy.
          </span>
          <a
            href={resolve(`/admin/terms/policy/new`)}
            class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-gray-800 transition-all flex items-center gap-2 shrink-0"
            >Create Policy <ArrowRightOutline size="md" class="text-orange" /></a
          >
        </div>
      </div>
    {/if}
    <form class="flex flex-col gap-4" onsubmit={handleSubmit}>
      <div>
        <Label for="name" class="mb-1">Agreement Policy Name</Label>
        <Helper class="mb-2"
          >This name will be used to identify agreement policies on the Admin Page and will not be
          displayed to users.</Helper
        >
        <Input
          type="text"
          name="name"
          id="name"
          placeholder="Agreement Policy Name"
          value={agreementPolicyToEdit?.name}
          disabled={$loading || preventEdits}
        />
      </div>
      <div>
        <Label for="agreement" class="mb-1">Agreement</Label>
        <Helper class="mb-2">Select which agreement to apply to this policy.</Helper>
        <Select
          items={availableAgreements}
          bind:value={selectedAgreement}
          placeholder="Select an agreement..."
          disabled={$loading || preventEdits}
        />
      </div>
      <div>
        <Label for="options" class="mb-1">Target Group</Label>
        <Helper class="mb-2"
          >Choose whether to show this agreement to all users or display to specific user groups.</Helper
        >
        <div class="flex flex-col gap-2">
          <Radio
            name="targetGroup"
            value="1"
            bind:group={selectedTargetGroupValue}
            disabled={preventEdits || $loading}>Display to all PingPong users.</Radio
          >
          <Radio
            name="targetGroup"
            value="2"
            bind:group={selectedTargetGroupValue}
            disabled={preventEdits || $loading}
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
            disabled={preventEdits || $loading}
          />
        </div>
      {/if}
      <Hr class="mt-8" />
      <div class="flex flex-row justify-end gap-4">
        <Button
          disabled={$loading}
          href={resolve(`/admin/terms`)}
          pill
          class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40"
          >Cancel</Button
        >
        <Button
          pill
          class="bg-orange border border-orange text-white hover:bg-orange-dark"
          type="submit"
          disabled={$loading || preventEdits}>Save</Button
        >
      </div>
    </form>
    <div></div>
  </div>
</div>
