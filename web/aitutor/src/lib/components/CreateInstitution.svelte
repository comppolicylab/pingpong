<script lang="ts">
  import { GradientButton, Textarea, Label, Input, Heading } from "flowbite-svelte";
  import { enhance } from "$app/forms";
  import { createEventDispatcher } from "svelte";

  const dispatch = createEventDispatcher();

  const done = () => {
    dispatch("close");
  };
</script>

<Heading tag="h2">Create a new institution</Heading>
  <form action="/?/createInstitution"
        method="POST"
        use:enhance
        class="flex flex-col gap-4"
        >
  <div>
  <Label for="name">Name</Label>
  <Input type="text" name="name" id="name" />
  </div>
  <div>
  <Label for="description">Description</Label>
  <Textarea name="description" id="description" />
  </div>
  <div>
  <Label for="logo">Logo</Label>
  <Input type="text" name="logo" id="logo" />
  </div>
  <div class="flex items-center">
    <GradientButton color="cyanToBlue" type="submit">Create</GradientButton>
    <GradientButton color="grayToGray" type="reset" on:click={done}>Close</GradientButton>
  </div>
</form>
