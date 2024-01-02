<script>
  import {goto} from '$app/navigation';
  import {page} from '$app/stores';
  import { Heading, P, Card, Modal } from 'flowbite-svelte';
  import CreateClass from '$lib/components/CreateClass.svelte';

  export let data;
  export let form;

  const close = () => goto(`/institution/${data.institution.id}`);

  $: isCreatingClass = $page.url.searchParams.has("new-class");
  $: {
    if (form?.$status < 300 && isCreatingClass) {
      close();
    }
  }
</script>

<div class="container py-8">
  <Heading tag="h2">{data.institution.name}</Heading>

  <Heading tag="h3">Classes</Heading>

  <div class="flex flex-wrap mt-8 gap-4">
    {#each (data.classes || []) as class_}
      <Card horizontal class="w-80 h-40" href="/institution/{data.institution.id}/class/{class_.id}">
        <Heading tag="h4">{class_.name}</Heading>
      </Card>
    {/each}
    {#if data?.me?.user?.super_admin}
      <Card horizontal class="w-80 h-40" href="/institution/{data.institution.id}/?new-class">
        <Heading tag="h4">Add new class</Heading>
        <P>Click here to add a new class to this institution.</P>
      </Card>
    {/if}
  </div>
</div>

<Modal bind:open={isCreatingClass} dismissable={false}>
  <CreateClass {form} on:close={close} />
</Modal>
