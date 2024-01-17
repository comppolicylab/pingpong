<script lang="ts">
  import {markdown} from "$lib/markdown";

  export let content = "";
</script>

<div>
  {@html markdown(content)}
</div>
