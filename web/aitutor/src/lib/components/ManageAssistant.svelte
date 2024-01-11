<script lang="ts">
  import * as api from "$lib/api";
  import {goto} from "$app/navigation";
  import {page} from "$app/stores";
  import {Helper, Button, Select, Checkbox, Label, MultiSelect, Input, Textarea, GradientButton} from "flowbite-svelte";
  import { enhance } from "$app/forms";

  export let files;
  export let assistant = null;

  const action = assistant ? "?/updateAssistant" : "?/createAssistant";

  let selectedFiles = (assistant?.files || []).map((file) => file.file_id);
  const models = api.languageModels.map((model) => ({ value: model, name: model }));
  const tools = [
    { value: "code_interpreter", name: "Code Interpreter" },
  ];
  const defaultTools = ["code_interpreter"];
  $: fileOptions = (files || []).map((file) => ({ value: file.file_id, name: file.name }));

  // Revert edits
  const reset = (e) => {
    e.preventDefault();
    goto($page.url.pathname);
  };
</script>

<form class="grid grid-cols-2 gap-2" {action} method="POST" use:enhance>
  <div>
    <Label for="name">Name</Label>
      <Input label="name" id="name" name="name" value={assistant?.name} />
  </div>
  <div>
    <Label for="model">Model</Label>
      <Select items={models} label="model" id="model" name="model" value={assistant?.model || models[0].value} />
  </div>
  <div class="col-span-2">
    <Label for="instructions">Instructions</Label>
      <Helper>This is the prompt the language model will use to generate responses.</Helper>
      <Textarea label="instructions" id="instructions" name="instructions" value={assistant?.instructions} />
  </div>
  <div class="col-span-2">
    <Label for="model">Tools</Label>
      <Helper>Select tools available to the assistant when generating a response.</Helper>
      <MultiSelect name="tools" items="{tools}" value={assistant?.tools || defaultTools} />
  </div>

  <div class="col-span-2">
    <Label for="model">Files</Label>
      <Helper>
        Select which files this assistant should use for grounding.
      </Helper>
      <MultiSelect name="files" items="{fileOptions}" bind:value={selectedFiles} />
  </div>

  <div class="col-span-2">
    <Checkbox label="published" id="published" name="published" checked={!!assistant?.published}>Publish</Checkbox>
    <Helper>By default only you can see and interact with this assistant. If you would like to share the assistant with the rest of your class, select this option.</Helper>
  </div>

  <input type="hidden" name="assistantId" value={assistant?.id} />

  <div class="border-t pt-4 mt-4 flex items-center col-span-2 ">
    <GradientButton color="cyanToBlue" type="submit">Save</GradientButton>
      {#if assistant}
        <Button href="/manageAssistants" color="red" class="ml-4" on:click={reset} on:touchstart={reset}>Cancel</Button>
      {/if}
  </div>
</form>
