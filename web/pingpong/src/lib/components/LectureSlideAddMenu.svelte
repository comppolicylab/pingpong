<script lang="ts">
	import { Dropdown, DropdownItem } from 'flowbite-svelte';
	import { FileImageOutline, PlusOutline, QuestionCircleOutline } from 'flowbite-svelte-icons';

	let {
		insertIndex,
		questionPosition = null,
		label,
		onInsertMedia = null,
		onAddQuestion = null
	}: {
		insertIndex: number;
		questionPosition?: number | null;
		label: string;
		onInsertMedia?: ((insertIndex: number) => void) | null;
		onAddQuestion?: ((position: number) => void) | null;
	} = $props();

	let open = $state(false);

	function addMaterial() {
		open = false;
		onInsertMedia?.(insertIndex);
	}

	function addQuestion() {
		if (questionPosition == null) return;
		open = false;
		onAddQuestion?.(questionPosition);
	}
</script>

<div class="flex w-7 shrink-0 items-center justify-center self-stretch">
	<button
		type="button"
		aria-label={label}
		title="Add content"
		class="group/add flex h-full w-full items-center justify-center rounded-lg text-gray-300 hover:bg-gray-50 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-900/15"
	>
		<span
			class="flex h-6 w-6 items-center justify-center rounded-full border border-dashed border-gray-300 bg-white group-hover/add:border-gray-700 group-hover/add:bg-gray-900 group-hover/add:text-white"
		>
			<PlusOutline class="h-3 w-3" />
		</span>
	</button>
	<Dropdown
		placement="top"
		strategy="fixed"
		bind:open
		class="z-50 w-56 overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-xl"
	>
		{#if onInsertMedia}
			<DropdownItem
				onclick={addMaterial}
				class="flex w-full items-start gap-3 px-3 py-2.5 text-left"
			>
				<span
					class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100"
				>
					<FileImageOutline class="h-4 w-4 text-gray-700" />
				</span>
				<span>
					<span class="block text-sm font-semibold text-gray-900">Add material</span>
					<span class="block text-xs text-gray-500">Image, GIF, or video</span>
				</span>
			</DropdownItem>
		{/if}
		{#if onAddQuestion && questionPosition != null}
			<DropdownItem
				onclick={addQuestion}
				class="flex w-full items-start gap-3 px-3 py-2.5 text-left"
			>
				<span
					class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100"
				>
					<QuestionCircleOutline class="h-4 w-4 text-gray-700" />
				</span>
				<span>
					<span class="block text-sm font-semibold text-gray-900">Add question</span>
					<span class="block text-xs text-gray-500">Knowledge check after this item</span>
				</span>
			</DropdownItem>
		{/if}
	</Dropdown>
</div>
