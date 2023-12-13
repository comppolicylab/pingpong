<script lang="ts">
  import logo from '../logo.svg?raw';

  export let size = 8;
  export let color = "amber-600";
</script>

<div class="w-{size} fill-{color}">
  {@html logo}
</div>
