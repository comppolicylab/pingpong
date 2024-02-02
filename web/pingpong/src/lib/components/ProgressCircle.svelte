<!-- Inspired by:
  -- https://svelte.dev/repl/f1437286b08d4890b9207180868ee37e?version=3.46.4
  -->
<script lang="ts">
  export let progress: number;

  $: angle = 360 * (progress / 100);
	$: background = `radial-gradient(white 50%, transparent 51%),
    conic-gradient(transparent 0deg ${angle}deg, gainsboro ${angle}deg 360deg),
    conic-gradient(orange 0deg, yellow 90deg, lightgreen 180deg, green);`;
	$: cssVarStyles = `--background:${background}`
</script>

<div class="progress-circle" style="{cssVarStyles}"></div>

<style lang="css">
.progress-circle {
  background: var(--background);
  border-radius: 50%;
  width: 1.5rem;
  height: 1.5rem;
	transition: all 500ms ease-in;
	will-change: transform;
}
</style>
