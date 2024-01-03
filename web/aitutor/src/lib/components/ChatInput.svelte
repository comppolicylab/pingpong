<script lang="ts">
  import {ButtonGroup, Input, GradientButton} from "flowbite-svelte";
  import {page} from "$app/stores";

  export let loading = false;

  const init = (el) => {
    el.focus();
    return {
      update: () => {
        el.focus();
      },
    };
  };
</script>

<ButtonGroup class="w-full">
  <Input id="message" autocomplete="off" name="message" placeholder="Ask me anything" let:props>
    <input type="text" use:init={$page.params.threadId} disabled={loading} {...props} />
  </Input>
  <GradientButton type="submit" color="cyanToBlue" class={loading ? "animate-pulse cursor-progress" : undefined}>Send</GradientButton>
</ButtonGroup>
