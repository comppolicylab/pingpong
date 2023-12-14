<script lang="ts">
  import {goto} from '$app/navigation';
  import {page} from '$app/stores';
  import {Modal, Heading, P, Card} from 'flowbite-svelte';
  import CreateInstitution from '$lib/components/CreateInstitution.svelte';

  export let data;
  export let form;

  const close = () => goto("/");

  $: isCreatingInstitution = $page.url.searchParams.has("new-institution");
  $: {
    if (form?.$status < 300 && isCreatingInstitution) {
      close();
    }
  }
</script>

<div class="container py-8">
  <Heading tag="h2">Welcome to AI Tutor</Heading>
    <div class="flex flex-wrap mt-8 gap-4">
      {#each data?.institutions as institution}
        <Card horizontal img={institution.logo} class="w-80 h-40" href={`/institution/${institution.id}`}>
          <Heading tag="h3" color="text-gray-900">{institution.name}</Heading>
          <P>{institution.description}</P>
        </Card>
      {/each}
      {#if data?.me?.user?.super_admin}
        <Card horizontal img="" class="w-80 h-40" href="/?new-institution">
          <Heading tag="h3" color="text-gray-900">Create new</Heading>
          <P>Click here to create a new institution</P>
        </Card>
      {/if}
    </div>
</div>

<Modal bind:open={isCreatingInstitution} dismissable={false}>
  <CreateInstitution on:close={close} />
</Modal>
