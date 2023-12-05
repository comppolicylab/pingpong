<script>
  import * as api from '$lib/api';
  import { List, Li, Card, MultiSelect, Textarea, Accordion, AccordionItem, Dropzone, Heading, Button, Label, Input } from "flowbite-svelte";
  import NewAssistant from "./NewAssistant.svelte";

  export let data;

  const assistants = data.assistants || [];

  const uploadFile = async (event) => {
    event.preventDefault();
    const fEl = document.getElementById('file');
    const file = fEl.files[0];
    if (!file) {
      return;
    }
    const response = await api.uploadFile(fetch, data.class.id, file)
    console.log(response);
  }
</script>

<div class="m-24 space-y-12 divide-y divide-gray-200 dark:divide-gray-700">
  <Heading size="1">Manage Class</Heading>
  <form action="/admin/institution/{data.institutionId}/class/{data.class.id}?/updateClass" class="pt-6" method="POST">
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
        {#each data.files as file}
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
          <form action="/admin/institution/{data.institutionId}/class/{data.class.id}?/uploadFile" method="POST" enctype="multipart/form-data">
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
    <div class="col-span-2">
        {#each assistants as assistant}
          <Card class="space-y-1">
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
            <span>todo</span>
          </Card>
        {/each}
      <div>
        <Card>
          <Heading tag="h4" class="pb-3">Add new AI assistant</Heading>
          <NewAssistant files={data.files} action="/admin/institution/{data.institutionId}/class/{data.class.id}?/createAssistant" />
        </Card>
      </div>
    </div>
  </div>
  <pre>{JSON.stringify(data, null, 2)}</pre>

</div>
