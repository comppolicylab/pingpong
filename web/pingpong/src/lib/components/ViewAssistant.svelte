<script lang="ts">
  import {page} from "$app/stores";
  import {copy} from "svelte-copy";
  import {toast} from "@zerodevx/svelte-toast";
  import {Heading, Label, Button, List, Li} from "flowbite-svelte";
  import {
    EyeOutline,
    EyeSlashOutline,
    LinkOutline,
  } from 'flowbite-svelte-icons';

  export let assistant;
  export let creator;

  // Get the full URL to use the assistant
  $: assistantLink = `${$page.url.protocol}//${$page.url.host}/class/${assistant.class_id}?assistant=${assistant.id}`;

  // Show info that we copied the link to the clipboard
  const showCopiedLink = (e) => {
    e.preventDefault();
    e.stopPropagation();
    toast.push("Copied link to clipboard", {
      duration: 1000,
    });
  };
</script>

<div class="flex flex-col gap-2">
  <Heading tag="h4" class="pb-3 flex justify-between">
    <div>
    {#if !assistant.published}
    <EyeSlashOutline class="inline-block w-6 h-6 mr-2 text-gray-300" />
    {:else}
    <EyeOutline class="inline-block w-6 h-6 mr-2 text-amber-600" />
    {/if}
    {assistant.name}
    </div>

    <button on:click|preventDefault={() => {}} on:svelte-copy={showCopiedLink} use:copy={assistantLink}><LinkOutline class="inline-block w-6 h-6 text-gray-700 hover:text-green-700 active:animate-ping" /></button>
  </Heading>
  <Label>Author</Label>
  <span>{creator.email}</span>
  <Label>Instructions</Label>
  <span>{assistant.instructions}</span>
  <Label>Model</Label>
  <span>{assistant.model}</span>
  <Label>Formatting</Label>
    <List>
      <Li>Latex: {assistant.use_latex || false}</Li>
    </List>
  <Label>Tools</Label>
  <List>
    {#each JSON.parse(assistant.tools) as tool}
      <Li>{tool.type}</Li>
    {/each}
  </List>
  <Label>Files</Label>
  <List>
    {#each assistant.files as file}
      <Li>{file.name}</Li>
    {/each}
  </List>
  <Label>Published</Label>
  <span>{assistant.published ? "Yes" : "No"}</span>
</div>
