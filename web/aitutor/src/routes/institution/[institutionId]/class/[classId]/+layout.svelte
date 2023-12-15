<script lang="ts">
  export let data;

  $: canManage = !!data?.me?.user?.super_admin;
</script>

{#if data.isConfigured || canManage}
<slot></slot>
{:else}
<div class="flex items-center justify-center h-full">
  <div class="text-center">
    <h1 class="text-2xl font-bold">No assistant configured</h1>
    <p class="text-gray-500">Please contact your class administrator</p>
  </div>
</div>
{/if}
