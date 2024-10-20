<script lang="ts">
  import { Button } from 'flowbite-svelte';

  export let message: string;
  export let actionText: string = 'Dismiss';
  export let onAction: () => void;
  export let onClose: () => void;
</script>

<div class="fixed bottom-4 left-1/2 transform -translate-x-1/2 w-full max-w-2xl px-4 z-50">
  <div class="bg-blue-100 text-blue-800 p-4 rounded-lg shadow-md flex items-center justify-between">
    <div class="flex-grow mr-4">
      {message}
    </div>
    <div class="flex items-center space-x-2">
      <Button color="blue" size="sm" on:click={onAction}>
        {actionText}
      </Button>
      <button on:click={onClose} class="text-blue-600 hover:text-blue-800 focus:outline-none">
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path
            fill-rule="evenodd"
            d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
            clip-rule="evenodd"
          />
        </svg>
      </button>
    </div>
  </div>
</div>
