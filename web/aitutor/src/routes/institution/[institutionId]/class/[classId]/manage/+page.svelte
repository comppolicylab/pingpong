<script>
  import {page} from '$app/stores';
  import {beforeNavigate} from '$app/navigation';
  import * as api from '$lib/api';
  import { List, Li, Card, MultiSelect, Textarea, Accordion, AccordionItem, Dropzone, Heading, Button, Label, Input } from "flowbite-svelte";
  import ManageAssistant from "$lib/components/ManageAssistant.svelte";
  import ViewAssistant from "$lib/components/ViewAssistant.svelte";

  export let data;

  $: editingAssistant = parseInt($page.url.searchParams.get('edit-assistant') || '0', 10);
  $: assistants = data?.assistants || [];
  $: files = data?.files || [];

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
  <Heading tag="h2">Manage Class</Heading>
  <form action="?/updateClass" class="pt-6" method="POST">
    <div class="grid grid-cols-3 gap-x-6 gap-y-8">
      <div>
        <Heading tag="h3">Class Details</Heading>
        <p>General information about the class.</p>
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
        <Button type="submit" color="dark">Save</Button>
      </div>
    </div>
  </form>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3">Teaching Team</Heading>
      <p>Manage teacher and course assistants.</p>
    </div>
    <pre>todo</pre>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3">Students</Heading>
      <p>Manage students in the class.</p>
    </div>
    <pre>todo</pre>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3">Files</Heading>
      <p>Manage files used by the automated tutors.</p>
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
            <Button color="dark" type="submit">Upload</Button>
          </form>
        </Li>
      </List>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8 pt-6">
    <div>
      <Heading tag="h3">AI Assistants</Heading>
      <p>Manage AI assistants.</p>
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
        {#if !editingAssistant && assistants.length == 0}
        <Card class="w-full max-w-full">
          <Heading tag="h4" class="pb-3">Add new AI assistant</Heading>
          <ManageAssistant {files} />
        </Card>
        {/if}
    </div>
  </div>
</div>
