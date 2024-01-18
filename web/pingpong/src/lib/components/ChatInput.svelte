<script lang="ts">
  import {ButtonGroup, Textarea, GradientButton} from "flowbite-svelte";
  import {page} from "$app/stores";
  import {ChevronUpSolid} from 'flowbite-svelte-icons';

  export let loading = false;
  export let maxHeight = 200;

  let ref;

  // Fix the height of the textarea to match the content.
  // The technique is to render an off-screen textarea with a scrollheight,
  // then set the height of the visible textarea to match. Other techniques
  // temporarily set the height to auto, but this causes the screen to flicker
  // and the other flow elements to jump around.
  const fixHeight = (el: HTMLTextAreaElement) => {
    if (!ref) {
      return;
    }
    ref.style.visibility = "hidden";
    ref.style.paddingRight = el.style.paddingRight;
    ref.style.width = `${el.clientWidth}px`;
    ref.value = el.value;
    const scrollHeight = ref.scrollHeight;
    el.style.height = `${scrollHeight + 8}px`;
  };

  // Focus textarea when component is mounted. Since we can only use `use` on
  // native DOM elements, we need to wrap the textarea in a div and then
  // access its child to imperatively focus it.
  const init = (el) => {
    el.children[0].focus();
    fixHeight(el);
    return {
      update: () => {
        el.children[0].focus();
      },
    };
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
  <Textarea id="message" rows="1" name="message" placeholder="Ask me anything" disabled={loading} on:keydown={maybeSubmit} on:input={e => fixHeight(e.target)}
                                                 style={`height: 48px; max-height: ${maxHeight}px; padding-right: 3rem; font-size: 1rem; line-height: 1.5rem;`}
    class="resize-none"
    />
    <textarea bind:this={ref} style="position: absolute; visibility: hidden; height: 0px; left: -1000px; top: -1000px" />
    <GradientButton type="submit" color="cyanToBlue" class={`${loading ? "animate-pulse cursor-progress" : ""} p-2 absolute bottom-3 right-2.5`}><ChevronUpSolid size="xs" /></GradientButton>
</div>
