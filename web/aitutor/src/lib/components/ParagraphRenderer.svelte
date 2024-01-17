<script lang="ts">
  import {renderMath} from "$lib/renderMath";

  export let text: string = "";
</script>

<p use:renderMath>
  {text}
</p>
