<script lang="ts">
  import {Heading, Label, List, Li} from "flowbite-svelte";
  export let assistant;
</script>

<div class="flex flex-col gap-2">
  <Heading tag="h4" class="pb-3">{assistant.name}</Heading>
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
