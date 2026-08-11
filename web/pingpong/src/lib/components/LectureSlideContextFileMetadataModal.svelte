<script lang="ts">
	import { Button, Helper, Label, Modal, Radio, Textarea } from 'flowbite-svelte';
	import * as api from '$lib/api';
	import {
		defaultLectureSlideContextFileMetadata,
		defaultUsageModeForKind,
		isLectureSlideContextFileMetadataValid,
		type LectureSlideContextFileEntry
	} from '$lib/lectureSlideContextFiles';
	import { humanSize } from '$lib/size';

	let {
		open = $bindable(false),
		files,
		onConfirm,
		onCancel
	}: {
		open?: boolean;
		files: File[];
		onConfirm: (entries: LectureSlideContextFileEntry[]) => void;
		onCancel: () => void;
	} = $props();

	let entries: LectureSlideContextFileEntry[] = $state([]);
	let submitted = $state(false);

	$effect(() => {
		entries = files.map((file) => ({
			file,
			metadata: defaultLectureSlideContextFileMetadata(file.name)
		}));
		submitted = false;
	});

	const allValid = $derived(
		entries.every((entry) => isLectureSlideContextFileMetadataValid(entry.metadata))
	);

	function setKind(index: number, file_kind: string) {
		const entry = entries[index];
		if (!entry || entry.metadata.file_kind === file_kind) return;
		entry.metadata.file_kind = file_kind;
		entry.metadata.usage_mode = defaultUsageModeForKind(file_kind);
	}

	function confirm() {
		if (!allValid) return;
		submitted = true;
		open = false;
		onConfirm(entries);
	}

	function cancel() {
		if (submitted) return;
		submitted = true;
		open = false;
		onCancel();
	}
</script>

<Modal size="lg" bind:open onclose={cancel} oncancel={cancel}>
	<div class="space-y-4">
		<div>
			<h3 class="text-lg font-semibold text-gray-900 dark:text-white">
				Add additional context files
			</h3>
			<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
				Tell the generator what each file is and how it should be used.
			</p>
		</div>
		{#each entries as entry, index (entry.file)}
			<div class="rounded-lg border border-gray-200 p-4 dark:border-gray-600">
				<div class="mb-3 flex items-baseline justify-between gap-2">
					<span class="truncate font-medium text-gray-900 dark:text-white" title={entry.file.name}>
						{entry.file.name}
					</span>
					<span class="shrink-0 text-sm text-gray-500">{humanSize(entry.file.size)}</span>
				</div>
				<Label class="mb-1">File type</Label>
				<div class="mb-3 flex gap-6">
					<Radio
						name="lecture-slide-context-kind-{index}"
						value={api.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT}
						checked={entry.metadata.file_kind === api.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT}
						onchange={() => setKind(index, api.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT)}
					>
						Transcript
					</Radio>
					<Radio
						name="lecture-slide-context-kind-{index}"
						value={api.LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER}
						checked={entry.metadata.file_kind === api.LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER}
						onchange={() => setKind(index, api.LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER)}
					>
						Other
					</Radio>
				</div>
				{#if entry.metadata.file_kind === api.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT}
					<Label class="mb-1">How should it be used?</Label>
					<div class="mb-3 space-y-2">
						<Radio
							name="lecture-slide-context-usage-{index}"
							value={api.LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL}
							bind:group={entry.metadata.usage_mode}
						>
							<span>
								Follow closely
								<Helper class="font-normal">
									Narration stays very close to the transcript, with only slight variations.
								</Helper>
							</span>
						</Radio>
						<Radio
							name="lecture-slide-context-usage-{index}"
							value={api.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE}
							bind:group={entry.metadata.usage_mode}
						>
							<span>
								General guide
								<Helper class="font-normal"
									>Guides content and pacing, but not word-for-word.</Helper
								>
							</span>
						</Radio>
						<Radio
							name="lecture-slide-context-usage-{index}"
							value={api.LECTURE_SLIDE_CONTEXT_FILE_USAGE_CUSTOM}
							bind:group={entry.metadata.usage_mode}
						>
							<span>
								Other
								<Helper class="font-normal">Explain how the transcript should be used.</Helper>
							</span>
						</Radio>
					</div>
				{/if}
				{#if entry.metadata.usage_mode === api.LECTURE_SLIDE_CONTEXT_FILE_USAGE_CUSTOM}
					<Label for="lecture-slide-context-note-{index}" class="mb-1">
						How should this file be used?
						{#if entry.metadata.file_kind !== api.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT}
							<span class="font-normal text-gray-500">(optional)</span>
						{/if}
					</Label>
					<Textarea
						id="lecture-slide-context-note-{index}"
						rows={2}
						maxlength={4000}
						placeholder="e.g., Use this only for key terminology."
						bind:value={entry.metadata.usage_note}
					/>
				{/if}
			</div>
		{/each}
		<div class="flex justify-end gap-2">
			<Button pill color="alternative" onclick={cancel}>Cancel</Button>
			<Button
				pill
				class="border border-orange-dark bg-orange text-white hover:bg-orange-dark"
				disabled={!allValid}
				onclick={confirm}
			>
				Upload {entries.length === 1 ? 'file' : `${entries.length} files`}
			</Button>
		</div>
	</div>
</Modal>
