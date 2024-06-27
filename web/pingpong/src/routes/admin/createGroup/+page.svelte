<script lang="ts">
  import { Select, Button, Label, Input, Heading, Helper } from 'flowbite-svelte';
  import * as api from '$lib/api';
  import { writable } from 'svelte/store';
  import { happyToast, sadToast } from '$lib/toast';
  import { goto } from '$app/navigation';

  export let data;

  const loading = writable(false);
  $: institutions = (data.admin.canCreateClass || []).sort((a, b) => a.name.localeCompare(b.name));
  let selectedInst = '';

  /**
   * Create a new class.
   */
  const submitCreateClass = async (evt: SubmitEvent) => {
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

    const term = d.term?.toString();
    if (!term) {
      $loading = false;
      return sadToast('Session is required');
    }

    let instId = parseInt(d.institution?.toString(), 10);
    if (!instId) {
      const newInst = d.newInstitution?.toString();
      if (!newInst) {
        $loading = false;
        return sadToast('Institution is required');
      }

      const rawInst = await api.createInstitution(fetch, { name: newInst });
      const instResponse = api.expandResponse(rawInst);
      if (instResponse.error) {
        $loading = false;
        return sadToast(instResponse.error.detail || 'Unknown error creating institution');
      }

      instId = instResponse.data.id;

      if (!instId) {
        $loading = false;
        return sadToast('Institution is required');
      }
    }

    const rawClass = await api.createClass(fetch, instId, { name, term });
    const classResponse = api.expandResponse(rawClass);
    if (classResponse.error) {
      $loading = false;
      return sadToast(classResponse.error.detail || 'Unknown error creating group');
    }

    $loading = false;
    form.reset();
    happyToast('Group created successfully!');
    await goto(`/group/${classResponse.data.id}/manage`);
  };
</script>

<div class="h-full w-full flex flex-col p-8 gap-8 items-center">
  <Heading tag="h2" class="serif">Create a new group</Heading>
  <form on:submit={submitCreateClass} class="flex flex-col gap-4 max-w-lg sm:min-w-[32rem]">
    <div>
      <Label for="name">Name</Label>
      <Input type="text" name="name" id="name" disabled={$loading} />
    </div>
    <div>
      <Label for="term">Session</Label>
      <Helper>Use this field to distinguish between groups that might be reoccuring, such as a class being offered every academic year.</Helper>
      <Input type="text" name="term" id="term" disabled={$loading} />
    </div>
    <div>
      <Label for="logo">Institution</Label>
      <Select name="institution" id="institution" bind:value={selectedInst} disabled={$loading}>
        {#each institutions as inst}
          <option value={inst.id}>{inst.name}</option>
        {/each}
        {#if data.admin.canCreateInstitution}
          <option disabled>──────────</option>
          <option value="0">+ Create new</option>
        {/if}
      </Select>
      {#if selectedInst === '0'}
        <div class="pt-4">
          <Label for="newInstitution">Institution name</Label>
          <Input type="text" name="newInstitution" id="new-inst" />
        </div>
      {/if}
    </div>
    <div class="flex items-center justify-between">
      <Button
        pill
        outline
        class="bg-white text-blue-dark-50 border-blue-dark-40 hover:bg-blue-light-40 hover:text-blue-dark-50"
        type="reset"
        disabled={$loading}
        href="/admin">Cancel</Button
      >
      <Button
        pill
        class="bg-orange text-white hover:bg-orange-dark"
        type="submit"
        disabled={$loading}>Create</Button
      >
    </div>
  </form>
</div>
