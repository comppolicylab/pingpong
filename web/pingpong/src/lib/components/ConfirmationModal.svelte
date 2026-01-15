<script lang="ts">
	import { Button } from 'flowbite-svelte';
	import { createEventDispatcher } from 'svelte';
	import { ExclamationCircleOutline } from 'flowbite-svelte-icons';


	interface Props {
		warningTitle: string;
		warningDescription: string;
		warningMessage: string;
		cancelButtonText: string;
		confirmText: string;
		confirmButtonText: string;
	}

	let {
		warningTitle,
		warningDescription,
		warningMessage,
		cancelButtonText,
		confirmText,
		confirmButtonText
	}: Props = $props();

	const dispatch = createEventDispatcher();
	let confirmInput = $state('');
</script>

<div class="px-2 text-center">
	<ExclamationCircleOutline class="mx-auto mb-4 h-12 w-12 text-red-600" />
	<h3 class="mb-5 text-xl font-bold break-words text-gray-900 dark:text-white">
		{warningTitle}
	</h3>
	<p class="mb-5 text-sm break-words whitespace-normal text-gray-700 dark:text-gray-300">
		{warningDescription}
		<span class="font-bold">{warningMessage}</span>
	</p>
	<div class="mb-4 px-4">
		<input
			type="text"
			class="block w-full rounded-lg border border-gray-300 bg-gray-50 py-2.5 text-sm text-gray-900 focus:border-blue-500 focus:ring-3 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400 dark:focus:border-blue-500 dark:focus:ring-blue-500"
			placeholder="Type '{confirmText}' to proceed"
			bind:value={confirmInput}
		/>
	</div>
	<div class="flex justify-center gap-4">
		<Button pill color="alternative" onclick={() => dispatch('cancel')}>{cancelButtonText}</Button>
		<Button
			pill
			outline
			color="red"
			disabled={confirmInput.toLowerCase() !== confirmText}
			onclick={() => dispatch('confirm')}
		>
			{confirmButtonText}
		</Button>
	</div>
</div>
