<script lang="ts">
	import { Progress as ProgressPrimitive } from 'bits-ui';
	import { cn, type WithoutChildrenOrChild } from '$lib/utils.js';

	interface ProgressProps extends WithoutChildrenOrChild<ProgressPrimitive.RootProps> {
		target?: number;
		showIndicators?: boolean;
		textClass?: string;
	}

	let {
		ref = $bindable(null),
		class: className,
		max = 100,
		value,
		target,
		showIndicators = false,
		textClass = 'text-xs',
		...restProps
	}: ProgressProps = $props();

	// Calculate positioning
	const currentPercent = $derived(((value ?? 0) / (max ?? 1)) * 100);
	const targetPercent = $derived(target !== undefined ? (target / (max ?? 1)) * 100 : 0);
	const currentIsBeforeTarget = $derived(target !== undefined && currentPercent < targetPercent);

	// Handle edge cases and proximity with better thresholds
	const currentAtLeftEdge = $derived(currentPercent <= 10);
	const currentAtRightEdge = $derived(currentPercent >= 90);
	const targetAtLeftEdge = $derived(target !== undefined && targetPercent <= 10);
	const targetAtRightEdge = $derived(target !== undefined && targetPercent >= 90);
	const isClose = $derived(target !== undefined && Math.abs(currentPercent - targetPercent) < 15);

	// Calculate transforms and positioning for current labels
	const currentLabelTransform = $derived(() => {
		if (currentAtLeftEdge) return 'translateX(0)';
		if (currentAtRightEdge) return 'translateX(-100%)';
		return currentIsBeforeTarget ? 'translateX(-100%)' : 'translateX(0)';
	});

	const currentMarginLeft = $derived(() => {
		if (currentAtLeftEdge) return '4px';
		if (currentAtRightEdge) return '-4px';
		return currentIsBeforeTarget ? '-4px' : '4px';
	});

	// Constrain current label position to prevent overflow
	const currentLabelLeft = $derived(() => {
		const percent = Math.max(0, Math.min(100, currentPercent));
		return `${percent}%`;
	});

	// Calculate transforms and positioning for target labels
	const targetLabelTransform = $derived(() => {
		if (targetAtLeftEdge) return 'translateX(0)';
		if (targetAtRightEdge) return 'translateX(-100%)';
		return !currentIsBeforeTarget ? 'translateX(-100%)' : 'translateX(0)';
	});

	const targetMarginLeft = $derived(() => {
		if (targetAtLeftEdge) return '4px';
		if (targetAtRightEdge) return '-4px';
		return !currentIsBeforeTarget ? '-4px' : '4px';
	});

	// Constrain target label position to prevent overflow
	const targetLabelLeft = $derived(() => {
		if (target === undefined) return '0%';
		const percent = Math.max(0, Math.min(100, targetPercent));
		return `${percent}%`;
	});
</script>

<div class="relative w-full {showIndicators ? (isClose ? 'py-12' : 'py-6') : ''}">
	{#if showIndicators}
		<!-- Current line extends above and below the bar -->
		<div
			class="absolute z-20 w-px bg-primary"
			style="left: {currentPercent}%; transform: translateX(-50%); top: {isClose
				? '1.5rem'
				: '0'}; bottom: {isClose ? '1.5rem' : '0'};"
		></div>

		<!-- Current label positioned left or right of line -->
		<div
			class="absolute z-20 font-medium whitespace-nowrap text-primary {textClass}"
			style="left: {currentLabelLeft()}; transform: {currentLabelTransform()}; margin-left: {currentMarginLeft()}; top: {isClose
				? '1.5rem'
				: '0'};"
		>
			Current
		</div>
		<div
			class="absolute z-20 font-medium whitespace-nowrap text-primary {textClass}"
			style="left: {currentLabelLeft()}; transform: {currentLabelTransform()}; margin-left: {currentMarginLeft()}; bottom: {isClose
				? '1.5rem'
				: '0'};"
		>
			{value ?? 0}%
		</div>

		<!-- Target line and labels -->
		{#if target !== undefined}
			<!-- Target line extends above and below the bar -->
			<div
				class="absolute top-0 bottom-0 z-20 w-px bg-muted-foreground"
				style="left: {targetPercent}%; transform: translateX(-50%);"
			></div>
			<!-- White target line segment where it crosses the filled bar -->
			{#if targetPercent <= currentPercent}
				<div
					class="absolute z-30 w-px bg-sidebar"
					style="left: {targetPercent}%; transform: translateX(-50%); top: calc(50% - 0.5rem); height: 1rem;"
				></div>
			{/if}

			<!-- Target label positioned left or right of line -->
			<div
				class="absolute top-0 z-20 font-medium whitespace-nowrap text-muted-foreground {textClass}"
				style="left: {targetLabelLeft()}; transform: {targetLabelTransform()}; margin-left: {targetMarginLeft()};"
			>
				Target
			</div>
			<div
				class="absolute bottom-0 z-20 font-medium whitespace-nowrap text-muted-foreground {textClass}"
				style="left: {targetLabelLeft()}; transform: {targetLabelTransform()}; margin-left: {targetMarginLeft()};"
			>
				{target}%
			</div>
		{/if}
	{/if}

	<ProgressPrimitive.Root
		bind:ref
		data-slot="progress"
		class={cn('relative h-2 w-full overflow-hidden rounded-full bg-primary/20', className)}
		{value}
		{max}
		{...restProps}
	>
		<div
			data-slot="progress-indicator"
			class="absolute inset-0 z-10 h-full w-full flex-1 bg-primary transition-all"
			style="transform: translateX(-{100 - (100 * (value ?? 0)) / (max ?? 1)}%)"
		></div>
		{#if target !== undefined}
			<div
				data-slot="progress-indicator"
				class="absolute inset-0 z-0 h-full w-full flex-1 bg-secondary transition-all"
				style="transform: translateX(-{100 -
					(100 * (target ?? 0)) /
						(max ??
							1)}%); background-image: repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(0,0,0,0.3) 4px, rgba(0,0,0,0.3) 8px);"
			></div>
		{/if}
	</ProgressPrimitive.Root>
</div>
