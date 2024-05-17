<script lang="ts">
  import { appMenuOpen } from '$lib/stores/general';
</script>

<div
  class={`main-panel transition-all absolute left-0 top-24 z-10 w-[calc(100%-2rem)] ml-4 mr-4 h-[calc(100%-6rem)] lg:h-full overflow-hidden lg:static ${
    $appMenuOpen ? 'left-[90%]' : ''
  }`}
>
  <div class="h-full flex-grow bg-white rounded-t-4xl overflow-hidden">
    <slot />
  </div>
</div>
