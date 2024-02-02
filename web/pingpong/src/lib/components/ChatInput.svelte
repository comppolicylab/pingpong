<script lang="ts">
  import {writable} from "svelte/store";
  import {ButtonGroup, Textarea, GradientButton} from "flowbite-svelte";
  import {page} from "$app/stores";
  import {ChevronUpSolid, PaperClipOutline} from 'flowbite-svelte-icons';
  import type {FileUploadInfo} from "$lib/api";
  import FilePlaceholder from "$lib/components/FilePlaceholder.svelte";

  export let disabled = false;
  export let loading = false;
  export let maxHeight = 200;
  export let upload: ((file: File, progress: (p: number) => void) => FileUploadInfo) | null = null;

  let ref;
  let uploadRef;
  let fileListRef;

  const files = writable<FileUploadInfo[]>([]);
  $: uploading = $files.some(f => f.state === "pending");
  $: fileIds = $files.filter(f => f.state === "success").map(f => f.response.file_id).join(",");

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
    ref.style.paddingLeft = el.style.paddingLeft;
    ref.style.width = `${el.clientWidth}px`;
    ref.value = el.value;
    const scrollHeight = ref.scrollHeight;
    const fileListHeight = $files.length ? fileListRef.clientHeight : 0;
    el.style.height = `${scrollHeight + 8 + fileListHeight}px`;
    el.style.paddingTop = `${12 + fileListHeight}px`;
  };

  // Focus textarea when component is mounted. Since we can only use `use` on
  // native DOM elements, we need to wrap the textarea in a div and then
  // access its child to imperatively focus it.
  const init = (el) => {
    document.getElementById("message").focus();
    return {
      update: () => {
        document.getElementById("message").focus();
      },
    };
  };

  // Submit form when Enter (but not Shift+Enter) is pressed in textarea
  const maybeSubmit = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled) {
        e.target.form.requestSubmit();
      }
    }
  };

  // Automatically upload files when they are selected.
  const autoupload = () => {
    if (!upload) {
      return;
    }

    // Run upload for every newly added file.
    const newFiles = Array.from(uploadRef.files).map(f => {
      const fp = upload(f, (progress) => {
        const idx = $files.findIndex(file => file.file === f);
        if (idx !== -1) {
          $files[idx].progress = progress;
        }
      });

      // Update the file list when the upload is complete.
      fp.promise.then((result) => {
        const idx = $files.findIndex(file => file.file === f);
        if (idx !== -1) {
          $files[idx].response = result;
          $files[idx].state = "success";
          $files[idx].id = result.id;
        }
      });

      return fp;
    });

    const curFiles = $files;
    $files = [...curFiles, ...newFiles];
  };

  // Fix the height of the container when the file list changes.
  const fixFileListHeight = () => {
    const update = () => {
      const el = document.getElementById("message");
      fixHeight(el);
    };
    return {update};
  };
</script>

<div use:init={$page.params.threadId} class="w-full relative rounded-lg border-[1px] border-solid border-cyan-500">
  <input type="hidden" name="file_ids" bind:value={fileIds} />
  <div class="absolute top-0 p-2 flex gap-2" use:fixFileListHeight={$files} bind:this={fileListRef}>
    {#each $files as file}
      <FilePlaceholder info={file} />
    {/each}
  </div>
  <div class="relative top-[2px]">
    <textarea id="message" rows="1" name="message"
                                  class="w-full !outline-none focus:ring-0 resize-none border-none bg-transparent pt-[12px] pb-[8px]"
                                  placeholder="Ask me anything" disabled={loading || disabled} on:keydown={maybeSubmit} on:input={e => fixHeight(e.target)}
                                                 style={`height: 48px; max-height: ${maxHeight}px; padding-right: 3rem; padding-left: 3.5rem; font-size: 1rem; line-height: 1.5rem;`}
      />
    <textarea bind:this={ref} style="position: absolute; visibility: hidden; height: 0px; left: -1000px; top: -1000px" />
    <label class="absolute bottom-3 left-2.5">
      <input type="file" multiple style="display: none;" bind:this={uploadRef} on:change={autoupload} />
      <GradientButton type="button" color="cyanToBlue" disabled={loading || disabled} class="p-2" on:click={() => uploadRef.click()}>
        <PaperClipOutline size="sm" />
      </GradientButton>
    </label>
    <GradientButton type="submit" color="cyanToBlue" class={`${loading ? "animate-pulse cursor-progress" : ""} p-2 absolute bottom-3 right-2.5`} disabled={uploading || loading || disabled}><ChevronUpSolid size="xs" /></GradientButton>
    </div>
</div>
