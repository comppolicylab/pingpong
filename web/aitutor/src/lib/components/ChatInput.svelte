<script lang="ts">
  import {ButtonGroup, Textarea, GradientButton} from "flowbite-svelte";
  import {page} from "$app/stores";

  export let loading = false;

  // Focus textarea when component is mounted. Since we can only use `use` on
  // native DOM elements, we need to wrap the textarea in a div and then
  // access its child to imperatively focus it.
  const init = (el) => {
    el.children[0].focus();
    return {
      update: () => {
        el.children[0].focus();
      },
    };
  };

  // Submit form when Enter (but not Shift+Enter) is pressed in textarea
  const checkKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      e.target.form.requestSubmit();
    }
  };
</script>

<ButtonGroup class="w-full">
  <div use:init={$page.params.threadId} class="w-full">
    <Textarea id="message" rows="1" name="message" placeholder="Ask me anything" disabled={loading} on:keydown={checkKey} />
  </div>
  <GradientButton type="submit" color="cyanToBlue" class={loading ? "animate-pulse cursor-progress" : undefined}>Send</GradientButton>
</ButtonGroup>
