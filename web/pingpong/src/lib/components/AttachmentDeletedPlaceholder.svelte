<script lang="ts">
	import { FileSolid } from 'flowbite-svelte-icons';

	
	interface Props {
		/**
	 * Information about a file that is being uploaded.
	 */
		file_id: string;
	}

	let { file_id }: Props = $props();
</script>

<div
	class="-delete-button-container relative flex cursor-default items-center rounded-lg border-[1px] border-solid border-gray-300 px-2 hover:shadow-sm"
>
	<div>
		<FileSolid class="h-6 w-6 text-red-500" />
	</div>
	<div class="flex flex-col p-2">
		<div class="text-xs font-bold text-gray-500">Unavailable File</div>
		<div class="text-xs text-gray-500">{file_id}</div>
	</div>
</div>
