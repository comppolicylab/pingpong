<script lang="ts">
	import logo from './canvas-logo.svg?raw';

	interface Props {
		size?: number | string;
		extraClass?: string;
	}

	let { size = 8, extraClass = '' }: Props = $props();
</script>

<div class="w-{size} {extraClass}">
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html logo}
</div>
