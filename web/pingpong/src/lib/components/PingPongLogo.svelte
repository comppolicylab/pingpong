<script lang="ts">
	import logo from './pingpong-logo.svg?raw';

	export let size: number | string = 8;
	export let extraClass = '';
</script>

<div class="w-{size} {extraClass}">
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html logo}
</div>
