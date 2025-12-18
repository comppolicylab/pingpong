<script lang="ts">
  import * as api from '$lib/api';
  import { loading } from '$lib/stores/general';
  import { happyToast, sadToast } from '$lib/toast';
  import { Button, Heading, Helper, Input, Label, Select, Modal } from 'flowbite-svelte';
  import { onMount } from 'svelte';
  import { ExclamationCircleOutline } from 'flowbite-svelte-icons';

  export let data;
  $: externalLoginProviders = data.externalLoginProviders;

  let openid_configuration: string | null = null;
  let registration_token: string | null = null;
  let missing_params = false;
  let showModal = false;

  onMount(() => {
    const params = new URLSearchParams(window.location.search);
    openid_configuration = params.get('openid_configuration');
    registration_token = params.get('registration_token');
    if (!openid_configuration || !registration_token) {
      missing_params = true;
      showModal = true;
    }
  });

  const handleSubmit = async (evt: SubmitEvent) => {
    evt.preventDefault();
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const name = d.name?.toString();
    if (!name) {
      $loading = false;
      return sadToast('Name is required');
    }

    const ssoId = d.sso_id?.toString();
    if (!ssoId) {
      $loading = false;
      return sadToast('SSO identifier is required');
    }

    const adminName = d.admin_name?.toString();
    if (!adminName) {
      $loading = false;
      return sadToast('Administrator name is required');
    }

    const adminEmail = d.admin_email?.toString();
    if (!adminEmail) {
      $loading = false;
      return sadToast('Administrator email is required');
    }

    const data: api.LTIRegisterRequest = {
      name: name,
      admin_name: adminName,
      admin_email: adminEmail,
      provider_id: parseInt(ssoId, 10),
      openid_configuration: openid_configuration || '',
      registration_token: registration_token || ''
    };

    const result = await api.registerLTIInstance(fetch, data);
    if (result.$status < 300) {
      happyToast('LTI instance registered successfully');
    } else {
      sadToast('There was an error registering the LTI instance');
    }
    $loading = false;
  };
</script>

<div class="h-full w-full flex flex-col p-8 gap-8 items-center overflow-y-auto">
  <Heading tag="h2" class="serif">Set up your LTI instance with PingPong</Heading>
  <form class="flex flex-col gap-4 max-w-lg sm:min-w-[32rem]" on:submit={handleSubmit}>
    <div>
      <Label for="name" class="mb-1">Instance name</Label>
      <Helper class="mb-2"
        >Use this field to give your LTI instance a name to help us identify it in the future.</Helper
      >
      <Input id="name" name="name" placeholder="Example University LMS" />
    </div>
    <div>
      <Label for="admin_name" class="mb-1">Administrator Name</Label>
      <Helper class="mb-2"
        >Let us know who we should contact if we need to troubleshoot your integration.</Helper
      >
      <Input id="admin_name" name="admin_name" placeholder="John Doe" />
    </div>
    <div>
      <Label for="admin_email" class="mb-1">Administrator Email</Label>
      <Input id="admin_email" name="admin_email" placeholder="john.doe@example.com" />
    </div>
    <div>
      <Label for="sso_id" class="mb-1">SSO Provider</Label>
      <Helper class="mb-2"
        >Use this field to select which SSO identifier Canvas will provide to PingPong. If PingPong
        does not support your SSO identifier, select "No SSO". PingPong will use SSO identifers and
        fallback to email addresses to identify users.<br /><br />PingPong relies on the
        <code class="font-mono">lis_person_sourcedid</code>
        attribute in the <code class="font-mono">NamesAndRoleMembership</code> object to get the user's
        SSO identifier.</Helper
      >
      <Select name="sso_id" id="sso_id" disabled={$loading}>
        {#each externalLoginProviders as provider}
          <option value={provider.id}>{provider.display_name || provider.name}</option>
        {/each}
        <option disabled>──────────</option>
        <option value="0">No SSO</option>
      </Select>
    </div>
    <div class="text-sm text-gray-600">
      <b>Note:</b> After you completete the LTI registration process, your integration will need to be
      reviewed by a PingPong administrator before it becomes active. You will receive an email when your
      integration is approved.
    </div>
    <div class="flex items-center justify-between">
      <Button
        pill
        class="bg-orange text-white hover:bg-orange-dark"
        type="submit"
        disabled={$loading}>Submit</Button
      >
    </div>
  </form>
</div>

<!-- Modal for missing parameters -->
<Modal bind:open={showModal} dismissable={!missing_params} size="md">
  <div class="text-center">
    <div class="mx-auto mb-4 h-14 w-14 text-red-600">
      <ExclamationCircleOutline class="w-14 h-14" />
    </div>
    <h3 class="mb-5 text-lg font-normal text-gray-500">Missing Required Parameters</h3>
    <p class="mb-5 text-sm text-gray-500">
      This page requires both <code class="font-mono bg-gray-100 px-1 rounded"
        >openid_configuration</code
      >
      and <code class="font-mono bg-gray-100 px-1 rounded">registration_token</code> parameters to be
      present in the URL.
    </p>
    <p class="mb-5 text-sm text-gray-500">
      Please ensure you are accessing this page through the proper LTI registration flow.
    </p>
    {#if !missing_params}
      <div class="flex justify-center gap-4">
        <Button color="light" on:click={() => (showModal = false)}>Close</Button>
      </div>
    {/if}
  </div>
</Modal>
