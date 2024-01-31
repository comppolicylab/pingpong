<script>
  import { onMount} from 'svelte';
  import {writable} from 'svelte/store';
  import {page} from '$app/stores';
  import {beforeNavigate} from '$app/navigation';
  import * as api from '$lib/api';
  import { Checkbox, Helper, Modal, Listgroup, GradientButton, Secondary, Span, List, Li, Card, MultiSelect, Textarea, Accordion, AccordionItem, Dropzone, Heading, Button, Label, Input } from "flowbite-svelte";
  import ManageUser from "$lib/components/ManageUser.svelte";
  import BulkAddUsers from "$lib/components/BulkAddUsers.svelte";
  import ViewUser from "$lib/components/ViewUser.svelte";
  import ManageAssistant from "$lib/components/ManageAssistant.svelte";
  import ViewAssistant from "$lib/components/ViewAssistant.svelte";
  import Info from "$lib/components/Info.svelte";
  import {PenOutline} from "flowbite-svelte-icons";
  import {toast} from "@zerodevx/svelte-toast";

  export let data;
  export let form;

  onMount(() => {
    // Show an error if the form failed
    // TODO -- more universal way of showing validation errors
    if (form?.$status >= 400) {
      toast.push(form?.detail || "An unknown error occurred", {
        duration: 5000,
        theme: {
          // Error color
          '--toastBackground': '#F87171',
          '--toastBarBackground': '#EF4444',
          '--toastColor': '#fff',
        },
      })
    } else if (form?.$status >= 200 && form?.$status < 300) {
      toast.push("Success!", {
        duration: 5000,
        theme: {
          // Success color
          '--toastBackground': '#A7F3D0',
          '--toastBarBackground': '#22C55E',
          '--toastColor': '#000',
        },
      })
    }
  });

  let ttModal = false;
  let studentModal = false;
  let anyCanCreate = data?.class?.any_can_create_assistant;
  const blurred = writable(true);
  $: publishOptMakesSense = anyCanCreate;
  $: apiKey = data.apiKey || '';
  $: apiKeyBlur = apiKey.substring(0,6) + '**************' + apiKey.substring(Math.max(6, apiKey.length - 6));
  $: editingAssistant = parseInt($page.url.searchParams.get('edit-assistant') || '0', 10);
  $: creators = data?.assistantCreators || {};
  $: assistants = data?.assistants || [];
  $: models = data?.models || [];
  $: files = data?.files || [];
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
      </div>

      <div></div>
      <div></div>
      <div>
        <GradientButton type="submit" color="cyanToBlue">Save</GradientButton>
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
      <List tag="ul" list="none" class="w-full divide-y divide-gray-200 dark:divide-gray-700">
        {#each files as file}
          <Li class="py-3 sm:py-4">
            <div class="flex flex-row justify-between gap-4 items-center">
              <div class="flex-1 basis-3/4 flex-grow font-bold">{file.name}</div>
              <div class="flex-1 basis-1/4 max-w-sm flex-shrink text-gray-400 text-right">
                {file.content_type}
              </div>
              <div>
                <form action="?/deleteFile" method="POST">
                  <input type="hidden" name="fileId" value="{file.id}" />
                  <GradientButton color="pinkToOrange" size="xs" type="submit">Delete</GradientButton>
                </form>
              </div>
            </div>
          </Li>
        {/each}
        <Li class="py-3 sm:py-4">
          <form action="?/uploadFile" method="POST" enctype="multipart/form-data">
            <Label for="file">Upload file</Label>
            <Input type="file" id="file" name="file" />
            <GradientButton color="cyanToBlue" type="submit">Upload</GradientButton>
          </form>
        </Li>
      </List>
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
            <ManageAssistant {files} {assistant} {models} canPublish={canPublishAssistant} />
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
          <ManageAssistant {files} {models} canPublish={canPublishAssistant} />
        </Card>
        {/if}
      {/if}
    </div>
  </div>
</div>
