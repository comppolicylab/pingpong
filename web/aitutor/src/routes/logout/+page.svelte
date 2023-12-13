<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  onMount(() => {
    // Just erase the cookie, since the server is stateless.
    document.cookie = 'session=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
    goto('/login');
  });
</script>

<div>
  Logging you out ...
</div>
