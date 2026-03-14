<script lang="ts">
	import logo from './elevenlabs.svg?raw';

	export let size: number | string = 8;
	export let extraClass = '';
</script>

<div class="w-{size} {extraClass} shrink-0">
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html logo}
</div>
