<script>
  import {writable} from 'svelte/store';
  import {page} from '$app/stores';
  import {beforeNavigate} from '$app/navigation';
  import * as api from '$lib/api';
  import { Listgroup, GradientButton, Secondary, Span, List, Li, Card, MultiSelect, Textarea, Accordion, AccordionItem, Dropzone, Heading, Button, Label, Input } from "flowbite-svelte";
  import ManageAssistant from "$lib/components/ManageAssistant.svelte";
  import ViewAssistant from "$lib/components/ViewAssistant.svelte";
  import Info from "$lib/components/Info.svelte";
  import {PenOutline} from "flowbite-svelte-icons";

  export let data;

  const blurred = writable(true);
  $: apiKey = data.apiKey || '';
  $: apiKeyBlur = apiKey.substring(0,6) + '**************' + apiKey.substring(Math.max(6, apiKey.length - 6));
  $: editingAssistant = parseInt($page.url.searchParams.get('edit-assistant') || '0', 10);
  $: assistants = data?.assistants || [];
  $: files = data?.files || [];
  $: students = (data?.classUsers || []).filter(u => u.title === 'student');
  $: tt = (data?.classUsers || []).filter(u => u.title !== 'student');

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
              {#if apiKey}
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
        <div class="text-gray-400">Teaching team has not been configured yet.</div>
      {:else}
      <Listgroup items={tt} let:item on:click={console.log}>
        {item.email}
      </Listgroup>
      {/if}
      <form action="?/manageUsers" method="POST">

      </form>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading customSize="text-xl font-bold" tag="h3"><Secondary class="text-xl">Students</Secondary></Heading>
      <Info>Manage students in the class.</Info>
    </div>
    <div class="col-span-2">
      {#if students.length === 0}
        <div class="text-gray-400">No students have been invited yet.</div>
      {:else}
      <Listgroup items={students} let:item on:click={console.log}>
        {item.email}
      </Listgroup>
      {/if}
      <form action="?/manageUsers" method="POST">

      </form>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3" customSize="text-xl font-bold"><Secondary class="text-xl">Files</Secondary></Heading>
      <Info>Manage files used by the automated tutors.</Info>
    </div>
    <div class="col-span-2">
      <List tag="ul" list="none" class="w-full divide-y divide-gray-200 dark:divide-gray-700">
        {#each files as file}
          <Li class="py-3 sm:py-4">
            <div class="flex flex-row">
              <div class="flex-1 basis-3/4 flex-grow font-bold">{file.name}</div>
              <div class="flex-1 basis-1/4 max-w-sm flex-shrink text-gray-400 text-right">
                {file.content_type}
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
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3" customSize="text-xl font-bold"><Secondary class="text-xl">AI Assistants</Secondary></Heading>
      <Info>Manage AI assistants.</Info>
    </div>
    <div class="col-span-2 flex flex-wrap gap-4">
        {#each assistants as assistant}
          {#if assistant.id == editingAssistant}
          <Card class="w-full max-w-full">
            <ManageAssistant {files} {assistant} />
          </Card>
          {:else}
          <Card class="w-full max-w-full space-y-2" href={`${$page.url.pathname}?edit-assistant=${assistant.id}`}>
            <ViewAssistant {assistant} />
          </Card>
          {/if}
        {/each}
        {#if !editingAssistant}
        <Card class="w-full max-w-full">
          <Heading tag="h4" class="pb-3">Add new AI assistant</Heading>
          <ManageAssistant {files} />
        </Card>
        {/if}
    </div>
  </div>
</div>
