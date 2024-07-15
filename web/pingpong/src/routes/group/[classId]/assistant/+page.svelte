<script lang="ts">
  import type { Assistant } from '$lib/api';
  import ViewAssistant from '$lib/components/ViewAssistant.svelte';
  import {
    Heading,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell
  } from 'flowbite-svelte';
  import { ArrowRightOutline, CirclePlusSolid } from 'flowbite-svelte-icons';

  export let data;

  $: hasApiKey = !!data?.class?.api_key;
  $: creators = data?.assistantCreators || {};
  // "Course" assistants are endorsed by the class. Right now this means
  // they are created by the teaching team and are published.
  let courseAssistants: Assistant[] = [];
  // "My" assistants are assistants created by the current user, except
  // for those that appear in "course" assistants.
  let myAssistants: Assistant[] = [];
  // "Other" assistants are non-endorsed assistants that are not created by the current user.
  // For most people this means published assistants from other students. For people with
  // elevated permissions, this could also mean private assistants.
  let otherAssistants: Assistant[] = [];
  $: {
    const allAssistants = data?.assistants || [];
    console.log('assistants', allAssistants);
    // Split all assistants into categories
    courseAssistants = allAssistants.filter((assistant) => assistant.endorsed);
    myAssistants = allAssistants.filter(
      (assistant) => assistant.creator_id === data.me.user!.id && !assistant.endorsed
    );
    otherAssistants = allAssistants.filter(
      (assistant) => assistant.creator_id !== data.me.user!.id && !assistant.endorsed
    );
  }
</script>

<div class="h-full w-full overflow-y-auto p-12">
  {#if !hasApiKey}
    <Heading tag="h2" class="font-serif mb-4 font-medium text-3xl text-dark-blue-40"
      >No API key.</Heading
    >
    <div>You must configure an API key for this group before you can create or use assistants.</div>
  {:else}
    {#if data.grants.canCreateAssistants}
      <Heading tag="h2" class="text-3xl font-serif mb-4 font-medium text-dark-blue-40"
        >Make a new assistant</Heading
      >
      <div class="bg-gold rounded-2xl p-8 mb-12 justify-between gap-12 items-start lg:flex">
        <p class="mb-4 font-light">
          Build your own AI chatbot for this group. You can customize it with specific knowledge,
          personality, and parameters to serve as a digital assistant for this group.
        </p>
        <a
          href="/group/{data.class.id}/assistant/new"
          class="text-sm text-blue-dark-50 shrink-0 flex items-center justify-center font-medium bg-white rounded-full p-2 px-4 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
          >Create new assistant <ArrowRightOutline size="md" class="orange inline-block" /></a
        >
      </div>
    {/if}

    <Heading tag="h2" class="text-3xl font-serif mb-4 font-medium text-dark-blue-40"
      >Your assistants</Heading
    >
    <div class="grid md:grid-cols-2 gap-4 mb-12">
      {#each myAssistants as assistant}
        <ViewAssistant
          {assistant}
          creator={creators[assistant.creator_id]}
          editable={data.editableAssistants.has(assistant.id)}
        />
      {:else}
        <div>No assistants</div>
      {/each}
    </div>

    <Heading tag="h2" class="text-3xl font-serif font-medium mb-4 text-dark-blue-40"
      >Group assistants</Heading
    >
    <div class="grid md:grid-cols-2 gap-4 mb-12">
      {#each courseAssistants as assistant}
        <ViewAssistant
          {assistant}
          creator={creators[assistant.creator_id]}
          editable={data.editableAssistants.has(assistant.id)}
        />
      {:else}
        <div>No group assistants</div>
      {/each}
    </div>

    <Heading tag="h2" class="text-3xl font-serif font-medium mb-4 text-dark-blue-40"
      >Other assistants</Heading
    >
    {#if otherAssistants.length === 0}
      <div>No other assistants</div>
    {:else}
      <Table>
        <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
          <TableHeadCell>Assistant Name</TableHeadCell>
          <TableHeadCell>Author</TableHeadCell>
          <TableHeadCell>Status</TableHeadCell>
          <TableHeadCell>Link</TableHeadCell>
          <TableHeadCell>Chat</TableHeadCell>
        </TableHead>
        <TableBody>
          {#each otherAssistants as assistant}
            <TableBodyRow>
              <TableBodyCell class="font-light">{assistant.name}</TableBodyCell>
              <TableBodyCell class="font-light"
                >{creators[assistant.creator_id]?.name || 'unknown'}</TableBodyCell
              >
              <TableBodyCell class="font-light"
                >{assistant.published ? 'Published' : 'Private'}</TableBodyCell
              >
              <TableBodyCell>
                {#if data.editableAssistants.has(assistant.id)}
                  <a
                    href="/group/{data.class.id}/assistant/{assistant.id}"
                    class="text-sm text-blue-dark-50 font-medium bg-blue-light-40 rounded-full p-1 px-3 hover:bg-blue-dark-40 hover:text-white transition-all"
                    >Edit</a
                  >
                {/if}
              </TableBodyCell>

              <TableBodyCell
                ><a
                  href="/group/{data.class.id}?assistant={assistant.id}"
                  class="flex items-center w-32 gap-2 text-sm text-white font-medium bg-orange rounded-full p-1 px-3 hover:text-blue-dark-100 hover:bg-blue-dark-40 hover:text-white transition-all"
                  >Start a chat <CirclePlusSolid size="sm" class="inline" /></a
                ></TableBodyCell
              >
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    {/if}
  {/if}
</div>
