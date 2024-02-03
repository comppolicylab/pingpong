<script lang="ts">
  import { onMount} from 'svelte';
  import {get, writable} from 'svelte/store';
  import {page} from '$app/stores';
  import {beforeNavigate} from '$app/navigation';
  import * as api from '$lib/api';
  import type {FileUploadInfo} from '$lib/api';
  import { Checkbox, Helper, Modal, Listgroup, GradientButton, Secondary, Span, List, Li, Card, MultiSelect, Textarea, Accordion, AccordionItem, Dropzone, Heading, Button, Label, Input } from "flowbite-svelte";
  import ManageUser from "$lib/components/ManageUser.svelte";
  import BulkAddUsers from "$lib/components/BulkAddUsers.svelte";
  import ViewUser from "$lib/components/ViewUser.svelte";
  import ManageAssistant from "$lib/components/ManageAssistant.svelte";
  import ViewAssistant from "$lib/components/ViewAssistant.svelte";
  import FileUpload from '$lib/components/FileUpload.svelte';
  import FilePlaceholder from '$lib/components/FilePlaceholder.svelte';
  import Info from "$lib/components/Info.svelte";
  import {PenOutline} from "flowbite-svelte-icons";
  import {sadToast, happyToast} from "$lib/toast";

  /**
   * Application data.
   */
  export let data;

  /**
   * Form submission.
   */
  export let form;

  onMount(() => {
    // Show an error if the form failed
    // TODO -- more universal way of showing validation errors
    if (form?.$status >= 400) {
      let msg = form?.detail || "An unknown error occurred";
      if (form?.field) {
        msg += ` (${form.field})`;
      }
      sadToast(msg);
    } else if (form?.$status >= 200 && form?.$status < 300) {
      happyToast(msg);
    }
  });

  let ttModal = false;
  let studentModal = false;
  let anyCanCreate = data?.class?.any_can_create_assistant;
  let assistants = [];
  const blurred = writable(true);
  let uploads = writable<FileUploadInfo[]>([]);
  const trashFiles = writable<number[]>([]);
  $: publishOptMakesSense = anyCanCreate;
  $: apiKey = data.apiKey || '';
  $: apiKeyBlur = apiKey.substring(0,6) + '**************' + apiKey.substring(Math.max(6, apiKey.length - 6));
  $: editingAssistant = parseInt($page.url.searchParams.get('edit-assistant') || '0', 10);
  $: creators = data?.assistantCreators || {};
  $: {
    assistants = data?.assistants || [];
    assistants.sort((a, b) => a.id - b.id);
  }
  $: models = data?.models || [];
  $: files = data?.files || [];
  $: allFiles = [...$uploads, ...files.map(f => ({
    state: "success",
    progress: 100,
    file: { type: f.content_type, name: f.name },
    response: f,
    promise: Promise.resolve(f),
  }))].filter(f => !$trashFiles.includes(f.response?.id));
  $: asstFiles = allFiles.filter(f => f.state === "success").map(f => f.response);
  $: console.log(asstFiles)
  $: students = (data?.classUsers || []).filter(u => u.title.toLowerCase() === 'student');
  $: tt = (data?.classUsers || []).filter(u => u.title.toLowerCase() !== 'student');
  $: classRole = (data?.me?.user?.classes || []).find(c => c.class_id === data.class.id)?.role || '';
  $: hasElevatedPerms = ['write', 'admin'].includes(classRole.toLowerCase());
  $: hasApiKey = !!data?.class?.api_key;
  $: canCreateAssistant = hasElevatedPerms || data?.class?.any_can_create_assistant;
  $: canPublishAssistant = hasElevatedPerms || data?.class?.any_can_publish_assistant;

  // Check if we are editing an assistant and prompt if so.
  beforeNavigate((nav) => {
    const isSaved = nav.to.url.searchParams.has('save');

    if (isSaved) {
      nav.to.url.searchParams.delete('save');
      return;
    }

    if (editingAssistant) {
      const really = confirm('You have not saved your changes to this assistant. Do you wish to discard them?');
      if (!really) {
        nav.cancel();
      }
    }
  });

  // Handle file deletion.
  const removeFile = async (evt) => {
    const file = evt.detail;
    if (file.state === "pending" || file.state === "deleting") {
      return;
    } else if (file.state === "error") {
      uploads.update(u => u.filter(f => f !== file));
    } else {
      $trashFiles = [...$trashFiles, file.response.id];
      const result = await api.deleteFile(fetch, data.class.id, file.response.id);
      if (result.$status >= 300) {
        $trashFiles = $trashFiles.filter(f => f !== file.response.id);
        sadToast(`Failed to delete file: ${result.detail || "unknown error"}`);
      }
    }
  };

  // Handle adding new files
  const handleNewFiles = (evt) => {uploads = evt.detail; };
  // Submit file upload
  const uploadFile = (f: File, onProgress: (p: number) => void) => {
    return api.uploadFile(data.class.id, f, {onProgress});
  }

</script>

<div class="container py-8 space-y-12 divide-y divide-gray-200 dark:divide-gray-700">
  <Heading tag="h2"><Span gradient>Manage Class</Span></Heading>
    {#if hasElevatedPerms}
    <form action="?/updateClass" class="pt-6" method="POST">
    <div class="grid grid-cols-3 gap-x-6 gap-y-8">
      <div>
        <Heading customSize="text-xl font-bold" tag="h3"><Secondary class="text-xl">Class Details</Secondary></Heading>
        <Info>General information about the class.</Info>
      </div>
      <div>
        <Label for="name">Name</Label>
        <Input label="Name" id="name" name="name" value="{data.class.name}" />
      </div>

      <div>
        <Label for="term">Term</Label>
        <Input label="Term" id="term" name="term" value="{data.class.term}" />
      </div>

      <div>
      </div>
      <Checkbox id="any_can_create_assistant" name="any_can_create_assistant" bind:checked="{anyCanCreate}">Allow anyone to create assistants</Checkbox>
        <Helper>When this is enabled, anyone in the class can create assistants. Otherwise, only teachers and admins can create assistants.</Helper>

      <div>
      </div>
      {#if publishOptMakesSense}
        <Checkbox id="any_can_publish_assistant" name="any_can_publish_assistant" checked="{data.class.any_can_publish_assistant}">
          Allow anyone to publish assistants
        </Checkbox>
      {:else}
        <Checkbox id="any_can_publish_assistant" name="any_can_publish_assistant" checked="{false}" disabled>
          Allow anyone to publish assistants
        </Checkbox>
      {/if}
          <Helper>When this is enabled, anyone in the class can share their own assistants with the rest of the class. Otherwise, only teachers and admins can share assistants.</Helper>

      <div></div>
      <div></div>
      <div>
        <GradientButton type="submit" color="cyanToBlue">Save</GradientButton>
      </div>
    </div>
  </form>

  <form action="?/updateApiKey" class="pt-6" method="POST" >
    <div class="grid grid-cols-3 gap-x-6 gap-y-8">
      <div>
        <Heading customSize="text-xl font-bold" tag="h3"><Secondary class="text-xl">Billing</Secondary></Heading>
        <Info>Manage OpenAI credentials</Info>
      </div>

      <div class="col-span-2">
        <Label for="apiKey">API Key</Label>
          <div class="w-full relative" class:cursor-pointer={$blurred}>
            <Input autocomplete="off" class={$blurred ? 'cursor-pointer' : undefined} label="API Key" id="apiKey" name="apiKey" value="{apiKey}" on:blur={() => $blurred = true} on:focus={() => $blurred = false} />
          {#if $blurred}
            <div class="cursor-pointer flex items-center gap-2 w-full h-full absolute top-0 left-0 bg-white font-mono pointer-events-none">
              {#if hasApiKey}
                <span>{apiKeyBlur}</span>
              {:else}
                <span class="text-gray-400">No API key set</span>
              {/if}
              <PenOutline size="sm" />
            </div>
          {/if}
        </div>

        {#if apiKey && !$blurred}
          <Helper>Note: changing the API key will break all threads and assistants in the class, so it is not currently supported.</Helper>
        {/if}
      </div>

      <div></div>
      <div></div>
      <div>
        <GradientButton type="submit" disabled={!!apiKey} color="cyanToBlue">Save</GradientButton>
      </div>
    </div>
  </form>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading customSize="text-xl font-bold" tag="h3"><Secondary class="text-xl">Teaching Team</Secondary></Heading>
      <Info>Manage teacher and course assistants.</Info>
    </div>
    <div class="col-span-2">
      {#if tt.length === 0}
        <div class="text-gray-400 mb-4">Teaching team has not been configured yet.</div>
      {:else}
        <div class="mb-4">
        <Listgroup items={tt} let:item>
          <ViewUser user={item} on:click={() => ttModal = item} on:touchstart={() => ttModal = item} />
        </Listgroup>
        </div>
      {/if}
      <GradientButton color="cyanToBlue" on:click={() => ttModal = true} on:touchstart={() => ttModal = true}>Invite teaching team</GradientButton>
      {#if ttModal}
        <Modal bind:open={ttModal} title="Manage the teaching team">
          <ManageUser on:cancel={() => ttModal = false} user={typeof ttModal === 'boolean' ? null : ttModal} />
        </Modal>
      {/if}
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading customSize="text-xl font-bold" tag="h3"><Secondary class="text-xl">Students</Secondary></Heading>
      <Info>Manage students in the class.</Info>
    </div>
    <div class="col-span-2">
      {#if students.length === 0}
        <div class="text-gray-400 mb-4">No students have been invited yet.</div>
      {:else}
      <div class="mb-4">
        <Listgroup active items={students} let:item>
          <ViewUser user={item} on:click={() => studentModal = item} on:touchstart={() => studentModal = item} />
      </Listgroup>
      </div>
      {/if}
      <GradientButton color="cyanToBlue" on:click={() => studentModal = true} on:touchstart={() => studentModal = true}>Invite students</GradientButton>
      {#if studentModal}
        <Modal bind:open={studentModal} title="Manage students">
          {#if typeof studentModal === 'boolean'}
            <BulkAddUsers on:cancel={() => studentModal = false} role="read" title="Student" />
          {:else}
            <ManageUser on:cancel={() => studentModal = false} user={studentModal} />
          {/if}
        </Modal>
      {/if}
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3" customSize="text-xl font-bold"><Secondary class="text-xl">Files</Secondary></Heading>
        <Info>Upload files for use in assistants.
        Files must be under 512MB. See the <a href="https://platform.openai.com/docs/api-reference/files/create" rel="noopener noreferrer" target="_blank">OpenAI API docs</a> for more information.
        </Info>
    </div>
    <div class="col-span-2">
      {#if !hasApiKey}
        <div class="text-gray-400 mb-4">You need to set an API key before you can upload files.</div>
      {:else}
        <div class="my-4">
          <FileUpload upload={uploadFile} on:change={handleNewFiles} />
        </div>
        <div class="flex gap-2 flex-wrap">
          {#each allFiles as file}
            <FilePlaceholder info={file} on:delete={removeFile} />
          {/each}
        </div>
      {/if}
    </div>
  </div>
    {/if}

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3" customSize="text-xl font-bold"><Secondary class="text-xl">AI Assistants</Secondary></Heading>
      <Info>Manage AI assistants.</Info>
    </div>
    <div class="col-span-2 flex flex-wrap gap-4">
      {#if !hasApiKey}
        <div class="text-gray-400 mb-4">You need to set an API key before you can create AI assistants.</div>
      {:else}
        {#each assistants as assistant}
          {#if assistant.id == editingAssistant}
          <Card class="w-full max-w-full">
            <form class="grid grid-cols-2 gap-2" action="?/updateAssistant" method="POST">
              <ManageAssistant files={asstFiles} {assistant} {models} canPublish={canPublishAssistant} />
            </form>
          </Card>
          {:else}
          <Card class="w-full max-w-full space-y-2" href={assistant.creator_id === data.me.user.id && canCreateAssistant ?`${$page.url.pathname}?edit-assistant=${assistant.id}` : null}>
            <ViewAssistant {assistant} creator={creators[assistant.creator_id]} />
          </Card>
          {/if}
        {/each}
        {#if !editingAssistant && canCreateAssistant}
        <Card class="w-full max-w-full">
          <Heading tag="h4" class="pb-3">Add new AI assistant</Heading>
          <form class="grid grid-cols-2 gap-2" action="?/createAssistant" method="POST">
            <ManageAssistant files={asstFiles} {models} canPublish={canPublishAssistant} />
          </form>
        </Card>
        {/if}
      {/if}
    </div>
  </div>
</div>
