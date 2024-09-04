<script lang="ts">
  import { Button } from 'flowbite-svelte';
  import { ExclamationCircleOutline } from 'flowbite-svelte-icons';
  import { createEventDispatcher } from 'svelte';

  export let canvasCourseCode: string = '';
  export let leftAction: string = 'Keep imported users';
  export let rightAction: string = 'Remove imported users';

  // Custom events
  const dispatch = createEventDispatcher();
</script>

<div class="text-center">
  <ExclamationCircleOutline class="mx-auto mb-4 text-red-600 w-12 h-12" />
  <h3 class="mb-5 text-xl text-black font-bold">
    Remove imported users from {canvasCourseCode || 'Canvas'}?
  </h3>
  <h4 class="mb-5 text-sm text-black font-normal">
    While Canvas Sync was active, PingPong imported all users in your Canvas roster. If you keep
    imported users, you can edit their roles or remove their access to this group at any time.
  </h4>
  <div class="flex flex-row gap-2 justify-center">
    <Button pill color="alternative" on:click={() => dispatch('keep')}>{leftAction}</Button>
    <Button pill color="red" on:click={() => dispatch('remove')}>{rightAction}</Button>
  </div>
</div>
