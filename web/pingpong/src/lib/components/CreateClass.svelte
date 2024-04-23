<script lang="ts">
  import { Select, Button, Label, Input, Heading } from 'flowbite-svelte';
  import { enhance } from '$app/forms';
  import { createEventDispatcher } from 'svelte';
  import type { Institution } from '$lib/api';

  export let institutions: Institution[] = [];

  const dispatch = createEventDispatcher();

  const done = () => dispatch('close');

  let selectedInst = '';
</script>

<Heading tag="h2" class="serif">Create a new class</Heading>
<form action="?/createClass" method="POST" use:enhance class="flex flex-col gap-4">
  <div>
    <Label for="name">Name</Label>
    <Input type="text" name="name" id="name" />
  </div>
  <div>
    <Label for="term">Term</Label>
    <Input type="text" name="term" id="term" />
  </div>
  <div>
    <Label for="logo">Institution</Label>
    <Select name="institution" id="institution" bind:value={selectedInst}>
      {#each institutions as inst}
        <option value={inst.id}>{inst.name}</option>
      {/each}
      <option value="0">Create new</option>
    </Select>
    {#if selectedInst === '0'}
      <div>
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
      on:click={done}
      on:touchstart={done}>Cancel</Button
    >
    <Button pill class="bg-orange text-white hover:bg-orange-dark" type="submit">Create</Button>
  </div>
</form>
