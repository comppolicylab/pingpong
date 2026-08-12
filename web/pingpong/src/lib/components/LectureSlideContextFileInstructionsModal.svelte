<script lang="ts">
	import { Button, Helper, Label, Modal, Textarea } from 'flowbite-svelte';

	let {
		open = $bindable(false),
		filename = '',
		instructions = '',
		onSave,
		onCancel
	}: {
		open?: boolean;
		filename?: string;
		instructions?: string;
		onSave: (instructions: string) => void;
		onCancel: () => void;
	} = $props();

	let draft = $state('');

	$effect(() => {
		if (open) {
			draft = instructions;
		}
	});

	function save() {
		open = false;
		onSave(draft.trim());
	}

	function cancel() {
		open = false;
		onCancel();
	}
</script>

<Modal size="md" bind:open onclose={cancel} oncancel={cancel}>
	<div class="space-y-4">
		<div>
			<h3 class="text-lg font-semibold text-gray-900 dark:text-white">Custom instructions</h3>
			{#if filename}
				<p class="truncate text-sm text-gray-500 dark:text-gray-400">{filename}</p>
			{/if}
		</div>
		<div>
			<Label for="lecture-slide-context-instructions" class="mb-1">
				How should this file be used?
			</Label>
			<Textarea
				id="lecture-slide-context-instructions"
				rows={4}
				maxlength={4000}
				placeholder="e.g., Use this only for key terminology and flow."
				bind:value={draft}
			/>
			<Helper class="pt-1">
				These instructions are used while generating slide questions, narration, and slide chat
				answers.
			</Helper>
		</div>
		<div class="flex justify-end gap-2">
			<Button pill color="alternative" onclick={cancel}>Cancel</Button>
			<Button
				pill
				class="border border-orange-dark bg-orange text-white hover:bg-orange-dark"
				onclick={save}
			>
				Save
			</Button>
		</div>
	</div>
</Modal>
