<script lang="ts">
	export let extraClasses = '';
	export let label: string;
	export let type: 'info' | 'success' | 'error' | 'warning' | 'default' = 'default';

	const baseClasses =
		'items-center justify-center rounded-full border px-2.5 py-0.25 text-[0.75rem]';

	let statusClasses = '';
	$: {
		switch (type) {
			case 'info':
				statusClasses = 'bg-white text-blue-800 border-blue-700';
				break;
			case 'success':
				statusClasses = 'bg-white text-green-800 border-green-700';
				break;
			case 'error':
				statusClasses = 'bg-white text-red-800 border-red-700';
				break;
			case 'warning':
				statusClasses = 'bg-white text-yellow-800 border-yellow-700';
				break;
			default:
				statusClasses = 'bg-white text-gray-800 border-gray-700';
		}
	}
	$: classes = `${baseClasses} ${statusClasses} ${extraClasses}`;
</script>

<span class={classes} aria-label={`${label} assistant`}>
	{label}
</span>
