<script lang="ts">
  import {ButtonGroup, Textarea, GradientButton} from "flowbite-svelte";
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
  <Textarea id="message" rows="1" name="message" placeholder="Ask me anything" let:props>
    <textarea use:init={$page.params.threadId} disabled={loading} {...props} />
  </Textarea>
  <GradientButton type="submit" color="cyanToBlue" class={loading ? "animate-pulse cursor-progress" : undefined}>Send</GradientButton>
</ButtonGroup>
