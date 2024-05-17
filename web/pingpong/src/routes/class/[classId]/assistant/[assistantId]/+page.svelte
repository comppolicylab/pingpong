<script lang="ts">
  import {
    Helper,
    Button,
    Select,
    Checkbox,
    Label,
    MultiSelect,
    Input,
    Heading,
    Textarea,
    type SelectOptionType
  } from 'flowbite-svelte';
  import type { Tool, ServerFile } from '$lib/api';
  import { beforeNavigate, goto } from '$app/navigation';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';

  export let data;

  let confirmBeforeLeaving = true;

  beforeNavigate((nav) => {
    // Confirm before leaving the page

    if (confirmBeforeLeaving && !confirm('Are you sure you want to leave this page?')) {
      nav.cancel();
      return;
    }
  });

  $: assistant = data.assistants.find((a) => a.id === data.assistantId) || null;
  $: canPublish = data.grants.canPublishAssistants;

  let loading = false;
  let selectedFiles = (assistant?.files || []).map((file) => file.file_id);
  const tools = [{ value: 'code_interpreter', name: 'Code Interpreter' }];
  const defaultTools = [{ type: 'code_interpreter' }];

  $: selectedTools = (
    assistant?.tools ? (JSON.parse(assistant.tools) as Tool[]) : defaultTools
  ).map((t) => t.type);
  $: modelOptions = (data.models || []).map((model) => ({ value: model.id, name: model.id }));
  $: allFiles = data.files.map((f) => ({
    state: 'success',
    progress: 100,
    file: { type: f.content_type, name: f.name },
    response: f,
    promise: Promise.resolve(f)
  }));
  $: asstFiles = allFiles
    .filter((f) => f.state === 'success')
    .map((f) => f.response) as ServerFile[];
  let fileOptions: SelectOptionType<string>[] = [];
  $: {
    const fileFilter = data.uploadInfo.getFileSupportFilter({
      code_interpreter: selectedTools.includes('code_interpreter'),
      retrieval: true
    });
    fileOptions = (asstFiles || [])
      .filter(fileFilter)
      .map((file) => ({ value: file.file_id, name: file.name }));
  }

  // Handle save / create assistant.
  const submitForm = async (evt: SubmitEvent) => {
    evt.preventDefault();
    loading = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const body = Object.fromEntries(formData.entries());

    const tools: api.Tool[] = [{ type: 'retrieval' }];
    if (body.tools?.toString()) {
      for (const tool of body.tools.toString().split(',')) {
        tools.push({ type: tool });
      }
    }

    const file_ids: string[] = body.files?.toString().split(',') || [];

    const params = {
      name: body.name.toString(),
      description: body.description.toString(),
      instructions: body.instructions.toString(),
      model: body.model.toString(),
      tools,
      file_ids,
      published: body.published?.toString() === 'on',
      use_latex: body.use_latex?.toString() === 'on',
      hide_prompt: body.hide_prompt?.toString() === 'on'
    };

    const result = !data.assistantId
      ? await api.createAssistant(fetch, data.class.id, params)
      : await api.updateAssistant(fetch, data.class.id, data.assistantId, params);
    const expanded = api.expandResponse(result);

    if (expanded.error) {
      // TODO(jnu): error message is hard to read right now, improve this.
      loading = false;
      sadToast(`Error: ${JSON.stringify(expanded.error, null, '  ')}`);
    } else {
      happyToast('Assistant saved');
      confirmBeforeLeaving = false;
      goto(`/class/${data.class.id}/assistant`, { invalidateAll: true });
    }
  };
</script>

<div class="h-full w-full overflow-y-auto p-12">
  <Heading tag="h2" class="text-3xl font-serif font-medium mb-6 text-blue-dark-40">
    {#if data.isCreating}
      New assistant
    {:else}
      Edit assistant
    {/if}
  </Heading>

  <form on:submit={submitForm}>
    <div class="mb-4">
      <Label for="name">Name</Label>
      <Input label="name" id="name" name="name" value={assistant?.name} />
    </div>
    <div class="mb-4">
      <Label for="model">Model</Label>
      <Select
        items={modelOptions}
        label="model"
        id="model"
        name="model"
        value={assistant?.model || modelOptions[0].value}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Label for="description">Description</Label>
      <Helper
        >Describe what this assistant does. This information is <strong>not</strong> included in the
        prompt, but <strong>is</strong> shown to users.</Helper
      >
      <Textarea
        label="description"
        id="description"
        name="description"
        value={assistant?.description}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Label for="instructions">Instructions</Label>
      <Helper>This is the prompt the language model will use to generate responses.</Helper>
      <Textarea
        label="instructions"
        id="instructions"
        name="instructions"
        rows="6"
        value={assistant?.instructions}
      />
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        id="hide_prompt"
        name="hide_prompt"
        checked={(assistant ? assistant.hide_prompt : false) || false}>Hide Prompt</Checkbox
      >
      <Helper
        >Hide the prompt from other users. When checked, only the teaching team and the assistant's
        creator will be able to see this prompt.</Helper
      >
    </div>
    <div class="col-span-2 mb-4">
      <Checkbox
        label="use_latex"
        id="use_latex"
        name="use_latex"
        checked={(assistant ? assistant.use_latex : true) || false}>Use LaTeX</Checkbox
      >
      <Helper>Enable LaTeX formatting for assistant responses.</Helper>
    </div>
    <div class="col-span-2 mb-4">
      <Label for="model">Tools</Label>
      <Helper>Select tools available to the assistant when generating a response.</Helper>
      <MultiSelect name="tools" items={tools} value={selectedTools} />
    </div>

    <div class="col-span-2 mb-4">
      <!-- TODO(jnu): support for uploading files here. -->
      <Label for="model">Files</Label>
      <Helper>Select which files this assistant should use for grounding.</Helper>
      <MultiSelect name="files" items={fileOptions} bind:value={selectedFiles} />
    </div>

    <div class="col-span-2 mb-4">
      <Checkbox
        label="published"
        id="published"
        disabled={!canPublish && !assistant?.published}
        name="published"
        checked={!!assistant?.published}>Publish</Checkbox
      >
      {#if !canPublish}
        <Helper
          >Publishing assistants has been disabled for this class. Contact your admin if you need to
          share this assistant.</Helper
        >
      {:else}
        <Helper
          >By default only you can see and interact with this assistant. If you would like to share
          the assistant with the rest of your class, select this option.</Helper
        >
      {/if}
    </div>

    <input type="hidden" name="assistantId" value={assistant?.id} />

    <div class="border-t pt-4 mt-4 flex items-center col-span-2">
      <Button
        pill
        class="bg-orange border border-orange text-white hover:bg-orange-dark"
        type="submit"
        disabled={loading}>Save</Button
      >
      <Button
        disabled={loading}
        href={`/class/${data.class.id}/assistant`}
        color="red"
        pill
        class="bg-blue-light-50 border rounded-full border-blue-dark-40 text-blue-dark-50 hover:bg-blue-light-40 ml-4"
        >Cancel</Button
      >
    </div>
  </form>
</div>
