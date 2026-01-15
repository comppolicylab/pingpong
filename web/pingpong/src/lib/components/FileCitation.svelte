<script lang="ts">
	import { Modal } from 'flowbite-svelte';
	import { FileSolid } from 'flowbite-svelte-icons';
	import Markdown from './Markdown.svelte';

	interface Props {
		name: string;
		quote: string;
	}

	let { name, quote }: Props = $props();
	let isOpen = $state(false);
</script>

<Modal bind:open={isOpen} title={`Text used from "${name}"`} autoclose outsideclose dismissable>
	<Markdown content={quote} syntax={true} />
</Modal>

<button
	class="relative flex items-center rounded-lg border-[1px] border-solid border-gray-300 bg-white px-2 hover:shadow-sm"
	onclick={() => (isOpen = true)}
	disabled={!quote}
>
	<div>
		<FileSolid class="h-6 w-6 text-green-500" />
	</div>
	<div class="flex flex-col items-start p-2">
		<div class="text-xs font-bold text-gray-500">{name}</div>
		<div class="text-xs text-gray-500">Citation</div>
	</div>
</button>
