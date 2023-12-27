<script lang="ts">
  import * as api from "$lib/api";
  import {goto} from "$app/navigation";
  import {page} from "$app/stores";
  import {Button, Select, Checkbox, Label, MultiSelect, Input, Textarea, GradientButton} from "flowbite-svelte";
  import { enhance } from "$app/forms";

  export let files;
  export let assistant = null;

  const action = assistant ? "?/updateAssistant" : "?/createAssistant";

  const models = api.languageModels.map((model) => ({ value: model, name: model }));
  const tools = [
    { value: "code_interpreter", name: "Code Interpreter" },
  ];
  $: fileOptions = (files || []).map((file) => ({ value: file.file_id, name: file.name }));
  $: selectedFiles = (assistant?.files || []).map((file) => file.file_id);

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
      <Textarea label="instructions" id="instructions" name="instructions" value={assistant?.instructions} />
  </div>
  <div>
    <Label for="model">Tools</Label>
      <MultiSelect name="tools" items="{tools}" value={assistant?.tools || []} />
  </div>

  <div class="col-span-2">
    <Label for="model">Files</Label>
      <MultiSelect name="files" items="{fileOptions}" value={selectedFiles} />
  </div>

  <input type="hidden" name="assistantId" value={assistant?.id} />

  <div class="border-t pt-4 mt-4 flex items-center col-span-2 ">
    <GradientButton color="cyanToBlue" type="submit">Save</GradientButton>
      {#if assistant}
        <Button href="/manageAssistants" color="alternative" class="ml-4" on:click={reset}>Cancel</Button>
      {/if}
  </div>
</form>
