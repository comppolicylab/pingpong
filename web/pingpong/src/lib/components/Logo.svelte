<script lang="ts">
	import logo from './logo.svg?raw';

	interface Props {
		size?: number;
		extraClass?: string;
	}

	let { size = 8, extraClass = 'fill-amber-600' }: Props = $props();
</script>

<div class="w-{size} {extraClass}">
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html logo}
</div>
