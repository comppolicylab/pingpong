<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { Modal, Heading, P, Card } from 'flowbite-svelte';
  import CreateClass from '$lib/components/CreateClass.svelte';

  export let data;
  export let form;

  const close = () => goto('/');

  $: isCreatingClass = $page.url.searchParams.has('new-class');
  $: classesMgr = data.classes;
  $: classes = classesMgr.classes;
  $: instMgr = data.institutions;
  $: institutions = instMgr.institutions;
  $: {
    if (form?.$status && form?.$status < 300 && isCreatingClass) {
      close();
    }
  }
</script>

<div class="container py-8 overflow-y-auto h-full">
  <Heading tag="h2">Welcome to PingPong!</Heading>
  <div class="flex flex-wrap mt-8 gap-4">
    {#each $classes as cls}
      <Card horizontal class="w-80 h-40" href={`/class/${cls.id}`}>
        <div class="flex flex-col w-full justify-between">
          <div class="flex flex-row justify-between">
            <Heading tag="h3" color="text-gray-900">{cls.name}</Heading>
            <P class="text-gray-400">{cls.term}</P>
          </div>
          <div class="text-amber-500 text-lg">
            {cls.institution?.name || 'Unknown institution'}
          </div>
        </div>
      </Card>
    {/each}
    {#if $institutions.length}
      <div data-sveltekit-preload-data="off">
        <Card horizontal img="" class="w-80 h-40" href="/?new-class">
          <Heading tag="h3" color="text-gray-900">Create new</Heading>
          <P>Click here to create a new class</P>
        </Card>
      </div>
    {/if}
  </div>
</div>

<Modal bind:open={isCreatingClass} dismissable={false}>
  <CreateClass institutions={$institutions} on:close={close} />
  {#if form && !form.success}
    <P class="text-red-600">Error: {form?.detail || `unknown (${form.$status})`}</P>
  {/if}
</Modal>
