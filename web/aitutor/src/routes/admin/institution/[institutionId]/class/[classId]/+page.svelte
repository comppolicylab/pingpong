<script>
  import * as api from '$lib/api';
  import { MultiSelect, Textarea, Accordion, AccordionItem, Dropzone, Heading, Button, Label, Input } from "flowbite-svelte";
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

<div class="m-24 space-y-12">
  <Heading size="1">Manage Class</Heading>
  <pre>{JSON.stringify(data, null, 2)}</pre>

  <form action="/admin/institution/{data.institutionId}/class/{data.class.id}?/updateClass" method="POST">
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

      <div>
        <Button type="submit">Save</Button>
      </div>
    </div>
  </form>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8">
    <div>
      <Heading tag="h3">Students</Heading>
      <p>Manage students in the class.</p>
    </div>
    <pre>todo</pre>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8">
    <div>
      <Heading tag="h3">Teaching Team</Heading>
      <p>Manage teacher and course assistants.</p>
    </div>
    <pre>todo</pre>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8">
    <div>
      <Heading tag="h3">Files</Heading>
      <p>Manage files used by the automated tutors.</p>
    </div>
    <div class="col-span-2">
      <ul>
        {#each data.files as file}
          <li>{file.name}</li>
        {/each}
      </ul>
      <div>
        <form action="/admin/institution/{data.institutionId}/class/{data.class.id}?/uploadFile" method="POST" enctype="multipart/form-data">
          <Label for="file">Upload file</Label>
          <Input type="file" id="file" name="file" />
          <Button color="dark" type="submit">Upload</Button>
        </form>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-3 gap-x-6 gap-y-8">
    <div>
      <Heading tag="h3">AI Assistants</Heading>
      <p>Manage AI assistants.</p>
    </div>
    <div class="col-span-2">
      <Accordion>
        {#each assistants as assistant}
          <AccordionItem>
            <span slot="header">{assistant.name}</span>
            <pre>{JSON.stringify(assistant, null, 2)}</pre>
          </AccordionItem>
        {/each}
      </Accordion>
      <div>
        <Heading tag="h4">Add new AI assistant</Heading>
          <NewAssistant files={data.files} action="/admin/institution/{data.institutionId}/class/{data.class.id}?/createAssistant" />
      </div>
    </div>
  </div>

</div>
