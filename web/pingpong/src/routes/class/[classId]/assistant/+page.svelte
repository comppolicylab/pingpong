<script lang="ts">
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

  export let data;

  $: hasApiKey = !!data?.class?.api_key;
  $: creators = data?.assistantCreators || {};
  $: allAssistants = data?.assistants || [];
  $: myAssistants = allAssistants.filter((a) => a.creator_id === data.me.user!.id);
  $: courseAssistants = allAssistants.filter((a) => a.endorsed);
  // "Other" assistants are non-endorsed assistants that are not created by the current user.
  // For most people this means published assistants from other students. For people with
  // elevated permissions, this could also mean private assistants.
  $: otherAssistants = allAssistants.filter(
    (a) => !a.endorsed && a.creator_id !== data.me.user!.id
  );
</script>

<div class="h-full w-full overflow-y-auto px-2">
  {#if !hasApiKey}
    <Heading tag="h2">No API key.</Heading>
    <div>You must configure an API key for this class before you can create or use assistants.</div>
  {:else}
    {#if data.grants.canCreateAssistants}
      <Heading tag="h2">Make a new assistant</Heading>
      <div>
        Click here to make a new assistant: <a href="/class/{data.class.id}/assistant/new"
          >Create new assistant</a
        >
      </div>
    {/if}

    <Heading tag="h2">Your assistants</Heading>
    <div>
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

    <Heading tag="h2">Course assistants</Heading>
    <div>
      {#each courseAssistants as assistant}
        <ViewAssistant
          {assistant}
          creator={creators[assistant.creator_id]}
          editable={data.editableAssistants.has(assistant.id)}
        />
      {:else}
        <div>No course assistants</div>
      {/each}
    </div>

    <Heading tag="h2">Other assistants</Heading>
    {#if otherAssistants.length === 0}
      <div>No other assistants</div>
    {:else}
      <Table>
        <TableHead>
          <TableHeadCell>Author</TableHeadCell>
          <TableHeadCell>Assistant Name</TableHeadCell>
          <TableHeadCell>Status</TableHeadCell>
          <TableHeadCell>Link</TableHeadCell>
          <TableHeadCell>Chat</TableHeadCell>
        </TableHead>
        <TableBody>
          {#each otherAssistants as assistant}
            <TableBodyRow>
              <TableBodyCell>{creators[assistant.creator_id]?.email || 'unknown'}</TableBodyCell>
              <TableBodyCell>{assistant.name}</TableBodyCell>
              <TableBodyCell>{assistant.published ? 'Published' : 'Private'}</TableBodyCell>
              <TableBodyCell>
                {#if data.editableAssistants.has(assistant.id)}
                  <a href="/class/{data.class.id}/assistant/{assistant.id}">Edit</a>
                {/if}
              </TableBodyCell>

              <TableBodyCell
                ><a href="/class/{data.class.id}?assistant={assistant.id}">Chat</a></TableBodyCell
              >
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    {/if}
  {/if}
</div>
