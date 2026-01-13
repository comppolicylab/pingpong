<script lang="ts">
  import { Button, CloseButton, Heading, Textarea } from 'flowbite-svelte';
  import { createEventDispatcher } from 'svelte';
  import SanitizeFlowbite from './SanitizeFlowbite.svelte';
  import PingPongLogo from './PingPongLogo.svelte';
  import { loading } from '$lib/stores/general';

  // Props
  export let open: boolean = false;
  export let code: string = '';
  export let preventEdits: boolean = false;

  // Event dispatcher
  const dispatch = createEventDispatcher();

  // Handle closing modal
  function closeModal() {
    dispatch('close');
  }

  // Handle click outside
  function handleClickOutside(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (target.classList.contains('modal-backdrop')) {
      closeModal();
    }
  }

  // Handle escape key
  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeModal();
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

{#if open}
  <!-- Backdrop -->
  <div class="fixed inset-0 z-40 bg-gray-900/50" aria-hidden="true" />

  <!-- Modal -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center overflow-auto"
    role="dialog"
    aria-modal="true"
  >
    <!-- Clickable overlay -->
    <button
      type="button"
      class="absolute inset-0 w-full h-full cursor-default modal-backdrop"
      aria-label="Close modal"
      on:click={handleClickOutside}
    />

    <!-- Modal content -->
    <div class="relative flex flex-col w-4/5 h-4/5 m-4 bg-white rounded-lg shadow">
      <div class="flex flex-row items-center justify-between p-4">
        <Heading tag="h3" class="w-full text-2xl font-semibold ml-2">User Agreement Preview</Heading
        >
        <CloseButton on:click={closeModal} label="Close modal" />
      </div>

      <div class="flex flex-row gap-0 w-full h-full">
        <div class="flex flex-col w-1/3 p-4 bg-gray-100">
          <Textarea
            id="code"
            rows={10}
            class="w-full h-full font-mono"
            bind:value={code}
            disabled={$loading || preventEdits}
            placeholder="Enter your HTML code here..."
          />
        </div>
        <div class="w-2/3 h-full grow overflow-y-auto">
          <div class="flex flex-col w-full min-h-full h-fit py-10 bg-blue-dark-50">
            <div class="flex items-center justify-center">
              <div class="flex flex-col w-11/12 lg:w-7/12 max-w-2xl rounded-4xl overflow-hidden">
                <header class="bg-blue-dark-40 px-12 py-8">
                  <Heading tag="h4" class="logo w-full text-center"
                    ><PingPongLogo size="full" /></Heading
                  >
                </header>
                <div class="px-12 py-8 bg-white">
                  <div class="flex flex-col gap-4">
                    <SanitizeFlowbite html={code} />
                    <div class="flex-row gap-4 text-center flex justify-end mt-4">
                      <Button
                        class="text-blue-dark-40 bg-white border border-blue-dark-40 rounded-full hover:bg-blue-dark-40 hover:text-white"
                        type="button">Exit PingPong</Button
                      >
                      <Button class="text-white bg-orange rounded-full hover:bg-orange-dark"
                        >Accept</Button
                      >
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
{/if}
