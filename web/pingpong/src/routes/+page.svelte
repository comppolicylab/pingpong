<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { Modal, Heading, P, Card } from 'flowbite-svelte';
  import CreateClass from '$lib/components/CreateClass.svelte';

  export let data;
  export let form;

  const close = () => goto('/');

  $: isCreatingClass = $page.url.searchParams.has('new-class');
  $: {
    if (form?.$status && form?.$status < 300 && isCreatingClass) {
      close();
    }
  }
  $: classes = (data.classes || []).sort((a, b) => a.name.localeCompare(b.name));
</script>

<div>
  <header class="bg-blue-light-50 p-8 pb-6">
    <Heading tag="h2" class="font-serif">Welcome to PingPong!</Heading>
  </header>
  <div class="flex flex-wrap gap-4 p-8">
    {#each classes as cls}
      <Card horizontal class="w-80 h-40" href={`/class/${cls.id}`}>
        <div class="flex flex-col w-full justify-between">
          <Heading tag="h3" color="text-lg text-gray-900">{cls.name}</Heading>
          <P class="text-gray-400">{cls.term}</P>
          <div class="text-orange text-md">
            {cls.institution?.name || 'Unknown institution'}
          </div>
        </div>
      </Card>
    {/each}

    {#if data.institutions.length > 0 || data.canCreateInstitution}
      <div data-sveltekit-preload-data="off">
        <Card horizontal img="" class="w-80 h-40" href="/?new-class">
          <Heading tag="h3" color="text-lg text-gray-900">Create new</Heading>
          <P>Click here to create a new class</P>
        </Card>
      </div>
    {/if}
  </div>
</div>

<Modal bind:open={isCreatingClass} dismissable={false}>
  <CreateClass institutions={data.institutions} on:close={close} />
  {#if form && !form.success}
    <P class="text-red-600">Error: {form?.detail || `unknown (${form.$status})`}</P>
  {/if}
</Modal>
