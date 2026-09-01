<script lang="ts">
	import { Button, Checkbox, Helper, Input, Label } from 'flowbite-svelte';
	import type { ElevenLabsTTSModel, ElevenLabsTTSProfile } from '$lib/api';

	export let id: string;
	export let title: string;
	export let description: string;
	export let profile: ElevenLabsTTSProfile;
	export let disabled = false;
	export let previewing = false;
	export let previewDisabled = false;
	export let sampleText = '';
	export let sampleAudioSrc = '';
	export let previewError = '';
	export let onPreview: () => void;

	const selectModel = (model: ElevenLabsTTSModel) => {
		profile = { ...profile, model };
	};
	const updateNumber = (
		field: 'stability' | 'similarity_boost' | 'style' | 'speed',
		value: number
	) => {
		profile = { ...profile, [field]: value };
	};
</script>

<section class="rounded-lg border border-gray-200 bg-white p-4">
	<div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
		<div>
			<div class="text-sm font-medium text-gray-900">{title}</div>
			<Helper>{description}</Helper>
		</div>
		<Button
			type="button"
			color="light"
			class="w-full shrink-0 sm:w-auto"
			disabled={disabled || previewDisabled || previewing}
			onclick={onPreview}>{previewing ? 'Generating…' : 'Preview'}</Button
		>
	</div>

	<div
		class="flex flex-col items-stretch gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4"
	>
		<div class="min-w-0">
			<Label for={`${id}-model`}>Model</Label>
			<Helper class="pt-1">
				{profile.model === 'eleven_v3'
					? 'Rich, expressive speech with contextual delivery.'
					: 'Natural, consistent speech optimized for real time.'}
			</Helper>
		</div>
		<div
			id={`${id}-model`}
			role="radiogroup"
			aria-label={`${title} model`}
			class="grid w-52 shrink-0 grid-cols-2 self-end rounded-lg border border-gray-300 bg-gray-100 p-1"
		>
			<button
				type="button"
				role="radio"
				aria-checked={profile.model === 'eleven_flash_v2_5'}
				class={`rounded-md px-2 py-1.5 text-xs font-medium ${profile.model === 'eleven_flash_v2_5' ? 'bg-white text-blue-700 shadow-sm' : 'text-gray-600'}`}
				{disabled}
				onclick={() => selectModel('eleven_flash_v2_5')}>Flash v2.5</button
			>
			<button
				type="button"
				role="radio"
				aria-checked={profile.model === 'eleven_v3'}
				class={`rounded-md px-2 py-1.5 text-xs font-medium ${profile.model === 'eleven_v3' ? 'bg-white text-blue-700 shadow-sm' : 'text-gray-600'}`}
				{disabled}
				onclick={() => selectModel('eleven_v3')}>Eleven v3</button
			>
		</div>
	</div>

	<div class="mt-4 grid gap-4 md:grid-cols-2">
		<div>
			<Label for={`${id}-stability`}>Stability</Label>
			<Input
				id={`${id}-stability`}
				type="number"
				min="0"
				max="1"
				step="0.05"
				value={profile.stability}
				{disabled}
				oninput={(event) => updateNumber('stability', Number(event.currentTarget.value))}
			/>
		</div>
		<div>
			<Label for={`${id}-similarity`}>Similarity boost</Label>
			<Input
				id={`${id}-similarity`}
				type="number"
				min="0"
				max="1"
				step="0.05"
				value={profile.similarity_boost}
				{disabled}
				oninput={(event) => updateNumber('similarity_boost', Number(event.currentTarget.value))}
			/>
		</div>
		<div>
			<Label for={`${id}-speed`}>Voice speed</Label>
			<Input
				id={`${id}-speed`}
				type="number"
				min="0.7"
				max="1.2"
				step="0.05"
				value={profile.speed}
				{disabled}
				oninput={(event) => updateNumber('speed', Number(event.currentTarget.value))}
			/>
		</div>
		<div>
			<Label for={`${id}-style`}>Style exaggeration</Label>
			<Input
				id={`${id}-style`}
				type="number"
				min="0"
				max="1"
				step="0.05"
				value={profile.style}
				{disabled}
				oninput={(event) => updateNumber('style', Number(event.currentTarget.value))}
			/>
		</div>
	</div>
	<div class="mt-3">
		<Checkbox
			id={`${id}-speaker-boost`}
			checked={profile.use_speaker_boost}
			{disabled}
			onchange={(event) =>
				(profile = { ...profile, use_speaker_boost: event.currentTarget.checked })}
			>Speaker boost</Checkbox
		>
	</div>

	{#if previewError}
		<div class="pt-3 text-sm text-red-700">{previewError}</div>
	{/if}
	{#if sampleAudioSrc}
		<div class="pt-3">
			<div class="mb-1 text-sm text-gray-700">Sample phrase: “{sampleText}”</div>
			<audio controls preload="auto" src={sampleAudioSrc} class="w-full"></audio>
		</div>
	{/if}
</section>
