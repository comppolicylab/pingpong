<script lang="ts">
	import { Tooltip } from 'flowbite-svelte';

	interface Props {
		version: number | null | undefined;
		extraClasses?: string;
		title?: string | null;
	}

	let { version, extraClasses = '', title = null }: Props = $props();

	const baseClasses =
		'inline-flex items-center rounded-full border px-2 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wide leading-none';
	const nextGenClasses = 'bg-blue-100 text-blue-800 border-blue-200';
	const classicClasses = 'bg-gray-100 text-gray-700 border-gray-200';

	let isNextGen = $derived((version ?? 0) >= 3);
	let label = $derived(isNextGen ? 'Next-Gen' : 'Classic');
	let classes =
		$derived(`${baseClasses} ${isNextGen ? nextGenClasses : classicClasses} ${extraClasses}`.trim());
	let tooltip =
		$derived(title ??
		(isNextGen
			? 'This assistant is using the latest Next-Gen architecture'
			: 'This assistant is using the previous Classic architecture'));
</script>

<span class={classes} aria-label={`${label} assistant`}>
	{label}
</span>
<Tooltip class="text-xs font-light xl:text-sm" arrow={false}>{tooltip}</Tooltip>
