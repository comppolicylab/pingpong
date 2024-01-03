<script lang="ts">
  import {goto} from '$app/navigation';
  import {page} from '$app/stores';
  import {Modal, Heading, P, Card} from 'flowbite-svelte';
  import CreateClass from '$lib/components/CreateClass.svelte';

  export let data;
  export let form;

  const close = () => goto("/");

  $: console.log("DATA", data);
  $: isCreatingClass = $page.url.searchParams.has("new-class");
  $: {
    if (form?.$status < 300 && isCreatingClass) {
      close();
    }
  }
</script>

<div class="container py-8">
  <Heading tag="h2">Welcome to AI Tutor</Heading>
    <div class="flex flex-wrap mt-8 gap-4">
      {#each data?.classes as cls}
        <Card horizontal img={cls.logo} class="w-80 h-40" href={`/class/${cls.id}`}>
          <Heading tag="h3" color="text-gray-900">{cls.name}</Heading>
          <P>{cls.description}</P>
        </Card>
      {/each}
      {#if data?.me?.user?.super_admin}
        <Card horizontal img="" class="w-80 h-40" href="/?new-class">
          <Heading tag="h3" color="text-gray-900">Create new</Heading>
          <P>Click here to create a new class</P>
        </Card>
      {/if}
    </div>
</div>

<Modal bind:open={isCreatingClass} dismissable={false}>
  <CreateClass on:close={close} />
</Modal>
