<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import * as api from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import { Button, Heading, Helper, Hr, Input, Label, Textarea } from 'flowbite-svelte';
  import { ArrowRightOutline, LockSolid } from 'flowbite-svelte-icons';
  import Modal from '$lib/components/CustomModal.svelte';
  import { resolve } from '$app/paths';

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
    const code = d.code?.toString();

    const params = {
      name,
      body: code
    };
    const rawAgreement = !userAgreementToEdit?.id
      ? await api.createAgreement(fetch, params)
      : await api.updateAgreement(fetch, userAgreementToEdit.id, params);
    const agreementResponse = api.expandResponse(rawAgreement);
    if (agreementResponse.error) {
      $loading = false;
      return sadToast(agreementResponse.error.detail || 'Unknown error saving agreement.');
    }
    happyToast('Agreement saved successfully!');
    await invalidateAll();
    await goto(resolve(`/admin/terms`));
    $loading = false;
  };

  let showCodeModal = false;
  let code = '';
  $: if (userAgreementToEdit?.body && !code) {
    code = userAgreementToEdit.body;
  }

  $: preventEdits = userAgreementToEdit?.policies && userAgreementToEdit.policies.length > 0;
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
        >{isCreating ? 'Create' : 'Edit'} User Agreement</Heading
      >
    </div>
    {#if preventEdits}
      <div
        class="flex col-span-2 items-center rounded-lg text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 p-4 mb-4"
      >
        <LockSolid class="w-8 h-8 mr-3" />
        <div class="flex flex-row justify-between items-center gap-5 w-full">
          <span>
            This Agreement is associated with one or more Agreement Policies and cannot be edited.<br
            />To make changes, create a new Agreement.
          </span>
          <a
            href={resolve(`/admin/terms/agreement/new`)}
            class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-gray-800 transition-all flex items-center gap-2 shrink-0"
            >Create Agreement <ArrowRightOutline size="md" class="text-orange" /></a
          >
        </div>
      </div>
    {/if}
    <form class="flex flex-col gap-4" onsubmit={handleSubmit}>
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
          placeholder="Agreement Name"
          value={userAgreementToEdit?.name}
          disabled={$loading || preventEdits}
        />
      </div>
      <div>
        <div class="flex flex-row justify-between items-end mb-1">
          <Label for="code">Agreement Content</Label><Button
            pill
            size="sm"
            class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full py-0.5 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
            disabled={$loading}
            onclick={() => (showCodeModal = true)}
          >
            {preventEdits ? 'Preview' : 'Edit with Preview'}
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
          rows={10}
          disabled={$loading || preventEdits}
          placeholder="Enter your HTML code here..."
        />
      </div>
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

<Modal bind:open={showCodeModal} onclose={() => (showCodeModal = false)} {preventEdits} bind:code />
