<script lang="ts">
  import {Heading, Label, List, Li} from "flowbite-svelte";
  import {
    EyeOutline,
    EyeSlashOutline,
  } from 'flowbite-svelte-icons';

  export let assistant;
  export let creator;
</script>

<div class="flex flex-col gap-2">
  <Heading tag="h4" class="pb-3">
    {#if !assistant.published}
    <EyeSlashOutline class="inline-block w-6 h-6 mr-2 text-gray-300" />
    {:else}
    <EyeOutline class="inline-block w-6 h-6 mr-2 text-amber-600" />
    {/if}
    {assistant.name}</Heading>
  <Label>Author</Label>
  <span>{creator.email}</span>
  <Label>Instructions</Label>
  <span>{assistant.instructions}</span>
  <Label>Model</Label>
  <span>{assistant.model}</span>
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
