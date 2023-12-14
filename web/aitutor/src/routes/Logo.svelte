<script lang="ts">
  import logo from '../logo.svg?raw';

  export let size = 8;
  export let extraClass = "fill-amber-600";
</script>

<div class="w-{size} {extraClass}">
  {@html logo}
</div>
