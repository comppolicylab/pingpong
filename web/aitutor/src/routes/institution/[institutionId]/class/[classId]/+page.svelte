<script lang="ts">
  import { goto } from "$app/navigation";
  import {GradientButton, ButtonGroup, Input} from "flowbite-svelte";
  import { enhance } from "$app/forms";

  export let data;
  export let form;

  $: {
    if (form?.$status < 300) {
      goto(`/institution/${data.institutionId}/class/${form.thread.class_id}/thread/${form.thread.id}`);
    }
  }
</script>

<div class="v-full h-full flex items-center">
  <div class="m-auto w-9/12">
    <form action="?/newThread" method="POST" use:enhance>
      <ButtonGroup class="w-full">
        <Input id="message" autocomplete="off" name="message" placeholder="Ask me anything" />
        <GradientButton type="submit" color="cyanToBlue">Send</GradientButton>
      </ButtonGroup>
    </form>
  </div>
</div>
