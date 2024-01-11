<script lang="ts">
  import {ButtonGroup, Textarea, GradientButton} from "flowbite-svelte";
  import {page} from "$app/stores";
  import {ChevronUpSolid} from 'flowbite-svelte-icons';

  export let loading = false;
  export let maxHeight = 200;
  export let defaultHeight = 40;

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

  const fixHeight = (e) => {
    const el = e.target;
    el.style.height = 0;
    const scrollHeight = el.scrollHeight;
    el.style.height = `${scrollHeight + 2}px`;
  };

  // Submit form when Enter (but not Shift+Enter) is pressed in textarea
  const maybeSubmit = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      e.target.form.requestSubmit();
    }
  };
</script>

<div use:init={$page.params.threadId} class="w-full relative">
  <Textarea id="message" rows="1" name="message" placeholder="Ask me anything" disabled={loading} on:keydown={maybeSubmit} on:input={fixHeight}
                                                 style={`max-height: ${maxHeight}px; padding-right: 3rem; font-size: 1rem; line-height: 1.5rem;`}
    class="resize-none"
    />
    <GradientButton type="submit" color="cyanToBlue" class={`${loading ? "animate-pulse cursor-progress" : ""} p-2 absolute bottom-3 right-2.5`}><ChevronUpSolid size="xs" /></GradientButton>
</div>
