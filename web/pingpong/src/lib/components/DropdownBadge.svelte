<script lang="ts">
    import { Badge } from 'flowbite-svelte';
    export let extraClasses = 'border-amber-400 from-amber-50 to-amber-100 text-amber-700';
  </script>
  
  <Badge
    class="flex flex-row items-center gap-x-1 py-0.5 px-2 border text-xs normal-case
           shadow-sm bg-gradient-to-b {extraClasses}"
    ><slot name="icon" /><slot name="name" /></Badge
  >