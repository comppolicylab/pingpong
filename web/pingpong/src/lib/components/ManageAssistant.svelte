<script lang="ts">
  import * as api from "$lib/api";
  import {goto} from "$app/navigation";
  import {page} from "$app/stores";
  import {Helper, Button, Select, Checkbox, Label, MultiSelect, Input, Textarea, GradientButton} from "flowbite-svelte";
  import { enhance } from "$app/forms";

  export let files;
  export let assistant = null;
  export let canPublish = true;

  const action = assistant ? "?/updateAssistant" : "?/createAssistant";

  let selectedFiles = (assistant?.files || []).map((file) => file.file_id);
  const models = api.languageModels.map((model) => ({ value: model, name: model }));
  const tools = [
    { value: "code_interpreter", name: "Code Interpreter" },
  ];
  const defaultTools = [{type: "code_interpreter"}];
  const selectedTools = (assistant?.tools ? JSON.parse(assistant.tools) : defaultTools).map(t => t.type);
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
    <Label for="description">Description</Label>
      <Helper>Describe what this assistant does. This information is <strong>not</strong> included in the prompt, but <strong>is</strong> shown to users.</Helper>
      <Textarea label="description" id="description" name="description" value={assistant?.description} />
  </div>
  <div class="col-span-2">
    <Label for="instructions">Instructions</Label>
      <Helper>This is the prompt the language model will use to generate responses.</Helper>
        <Textarea label="instructions" id="instructions" name="instructions" rows="6" value={assistant?.instructions} />
  </div>
  <div class="col-span-2">
    <Checkbox id="hide_prompt" name="hide_prompt" checked={assistant ? assistant.hide_prompt : false}>Hide Prompt</Checkbox>
    <Helper>Hide the prompt from other users. When checked, only the teaching team and the assistant's creator will be able to see this prompt.</Helper>
  </div>
  <div class="col-span-2">
    <Checkbox label="use_latex" id="use_latex" name="use_latex" checked={assistant ? assistant.use_latex: true}>Use LaTeX</Checkbox>
    <Helper>Enable LaTeX formatting for assistant responses.</Helper>
  </div>
  <div class="col-span-2">
    <Label for="model">Tools</Label>
      <Helper>Select tools available to the assistant when generating a response.</Helper>
      <MultiSelect name="tools" items="{tools}" value={selectedTools} />
  </div>

  <div class="col-span-2">
    <Label for="model">Files</Label>
      <Helper>
        Select which files this assistant should use for grounding.
      </Helper>
      <MultiSelect name="files" items="{fileOptions}" bind:value={selectedFiles} />
  </div>

  <div class="col-span-2">
    <Checkbox label="published" id="published" disabled={!canPublish && !assistant?.published} name="published" checked={!!assistant?.published}>Publish</Checkbox>
    {#if !canPublish}
      <Helper>Publishing assistants has been disabled for this class. Contact your admin if you need to share this assistant.</Helper>
    {:else}
      <Helper>By default only you can see and interact with this assistant. If you would like to share the assistant with the rest of your class, select this option.</Helper>
    {/if}
  </div>

  <input type="hidden" name="assistantId" value={assistant?.id} />

  <div class="border-t pt-4 mt-4 flex items-center col-span-2 ">
    <GradientButton color="cyanToBlue" type="submit">Save</GradientButton>
      {#if assistant}
        <Button href="/manageAssistants" color="red" class="ml-4" on:click={reset} on:touchstart={reset}>Cancel</Button>
      {/if}
  </div>
</form>
