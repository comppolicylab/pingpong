<script lang="ts">
  import {renderMath} from "$lib/renderMath";

  export let text: string = "";
</script>

<li use:renderMath>
  {text}
</li>
