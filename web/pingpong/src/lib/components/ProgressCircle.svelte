<!-- Inspired by:
  -- https://svelte.dev/repl/f1437286b08d4890b9207180868ee37e?version=3.46.4
  -->
<script lang="ts">
	interface Props {
		progress: number;
	}

	let { progress }: Props = $props();

	let angle = $derived(360 * (progress / 100));
	let background = $derived(`radial-gradient(white 50%, transparent 51%),
    conic-gradient(transparent 0deg ${angle}deg, gainsboro ${angle}deg 360deg),
    conic-gradient(#7dd3fc 0deg, #0ea5e9 90deg, #0284c7 180deg, #075985);`);
	let cssVarStyles = $derived(`--background:${background}`);
</script>

<div class="progress-circle" style={cssVarStyles}></div>

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
