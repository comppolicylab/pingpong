<script lang="ts">
  import { Button } from 'flowbite-svelte';
  import { createEventDispatcher } from 'svelte';
  import { ExclamationCircleOutline } from 'flowbite-svelte-icons';

  export let warningTitle: string;
  export let warningDescription: string;
  export let warningMessage: string;
  export let cancelButtonText: string;
  export let confirmText: string;

  export let confirmButtonText: string;

  const dispatch = createEventDispatcher();
  let confirmInput = '';
</script>

<div class="text-center px-2">
  <ExclamationCircleOutline class="mx-auto mb-4 text-red-600 w-12 h-12" />
  <h3 class="mb-5 text-xl text-gray-900 dark:text-white font-bold break-words">
    {warningTitle}
  </h3>
  <p class="mb-5 text-sm text-gray-700 dark:text-gray-300 break-words whitespace-normal">
    {warningDescription}
    <span class="font-bold">{warningMessage}</span>
  </p>
  <div class="mb-4 px-4">
    <input
      type="text"
      class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:ring-3 focus:border-blue-500 block w-full py-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500"
      placeholder="Type '{confirmText}' to proceed"
      bind:value={confirmInput}
    />
  </div>
  <div class="flex justify-center gap-4">
    <Button pill color="alternative" on:click={() => dispatch('cancel')}>{cancelButtonText}</Button>
    <Button
      pill
      outline
      color="red"
      disabled={confirmInput.toLowerCase() !== confirmText}
      on:click={() => dispatch('confirm')}
    >
      {confirmButtonText}
    </Button>
  </div>
</div>
