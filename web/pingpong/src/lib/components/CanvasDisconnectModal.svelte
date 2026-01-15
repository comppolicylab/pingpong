<script lang="ts">
	import { Button } from 'flowbite-svelte';
	import { ExclamationCircleOutline } from 'flowbite-svelte-icons';
	import { createEventDispatcher } from 'svelte';

	interface Props {
		canvasCourseCode?: string;
		leftAction?: string;
		rightAction?: string;
	}

	let {
		canvasCourseCode = '',
		leftAction = 'Keep imported users',
		rightAction = 'Remove imported users'
	}: Props = $props();

	// Custom events
	const dispatch = createEventDispatcher();
</script>

<div class="text-center">
	<ExclamationCircleOutline class="mx-auto mb-4 h-12 w-12 text-red-600" />
	<h3 class="mb-5 text-xl font-bold text-black">
		Remove imported users from {canvasCourseCode || 'Canvas'}?
	</h3>
	<h4 class="mb-5 text-sm font-normal text-black">
		While Canvas Sync was active, PingPong imported all users in your Canvas roster. If you keep
		imported users, you can edit their roles or remove their access to this group at any time.
	</h4>
	<div class="flex flex-row justify-center gap-2">
		<Button pill color="alternative" onclick={() => dispatch('keep')}>{leftAction}</Button>
		<Button pill color="red" onclick={() => dispatch('remove')}>{rightAction}</Button>
	</div>
</div>
