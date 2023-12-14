<script>
  import {Select, Label, MultiSelect, Input, Textarea, Button} from "flowbite-svelte";
  import { enhance } from "$app/forms";

  export let files;

  const models = [
    "gpt-4-1106-preview",
  ].map((model) => ({ value: model, name: model }));
  const tools = [
    { value: "code_interpreter", name: "Code Interpreter" },
  ];
  let fileOptions = [];

  $: {
    fileOptions = (files || []).map((file) => ({ value: file.file_id, name: file.name }));
  }
</script>

<form class="flex flex-col space-y-4" action="?/createAssistant" method="POST" use:enhance>
  <div>
    <Label for="name">Name</Label>
    <Input label="name" id="name" name="name" />
  </div>
  <div>
    <Label for="instructions">Instructions</Label>
    <Textarea label="instructions" id="instructions" name="instructions" />
  </div>
  <div>
    <Label for="model">Model</Label>
    <Select items={models} label="model" id="model" name="model" />
  </div>
  <div>
    <Label for="model">Tools</Label>
    <MultiSelect name="tools" items="{tools}" />
  </div>
  <div>
    <Label for="model">Files</Label>
    <MultiSelect name="files" items="{fileOptions}" />
  </div>
  <div>
    <Button color="dark" type="submit">Add</Button>
  </div>
</form>
