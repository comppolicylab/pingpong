<script lang="ts">
	import { ArrowUpOutline, ChevronDownOutline } from 'flowbite-svelte-icons';
	import { afterUpdate, setContext, tick } from 'svelte';
	import { writable } from 'svelte/store';

	// Whether to show the footer.
	export let footer = false;
	// Whether the dropdown is open.
	export let dropdownOpen = false;
	// The placeholder text shown in the dropdown button.
	export let placeholder = 'Select an option...';
	// The selected option.
	export let selectedOption: string;
	// The option nodes.
	export let optionNodes: Record<string, HTMLElement> = {};
	// The class of the header for each node, if any.
	export let optionHeaders: Record<string, string> = {};
	// The width of the dropdown as measured by the button width. Defaults to 3/5.
	export let width = 'max-w-150';
	// Whether the dropdown is disabled.
	export let disabled = false;
	// Where to align the selected option when the dropdown opens.
	export let selectedOptionScrollAlign: 'top' | 'center' | 'keep-visible' = 'top';
	// Optional label to show when options exist above the current scroll position.
	export let topOverflowLabel = '';
	const activeUrlStore = writable('');
	setContext('DropdownType', {
		activeClass:
			'text-primary-700 dark:text-primary-700 hover:text-primary-900 dark:hover:text-primary-900'
	});
	setContext('activeUrl', activeUrlStore);

	let dropdownRoot: HTMLElement;
	let dropdownContainer: HTMLElement;
	let previousDropdownOpen = false;
	let previousSelectedOption = '';
	let topOverflowLabelOpacity = 0;
	let topOverflowLabelOffset = 0;

	const TOP_OVERFLOW_LABEL_THRESHOLD = 8;
	const TOP_OVERFLOW_LABEL_FADE_START_VISIBLE_PX = 20;
	const TOP_OVERFLOW_LABEL_FADE_RANGE_PX = 28;

	function clamp(value: number, min: number, max: number) {
		return Math.min(Math.max(value, min), max);
	}

	function getStickyHeaderHeight(headerClass?: string) {
		if (!dropdownContainer || !headerClass) {
			return 0;
		}

		let totalStickyHeight = 0;
		const stickyHeaders = dropdownContainer.querySelectorAll(`.${headerClass}`);
		stickyHeaders.forEach((header) => {
			totalStickyHeight += (header as HTMLElement).offsetHeight;
		});
		return totalStickyHeight;
	}

	function getActiveStickyHeaderOffset() {
		if (!dropdownContainer) {
			return 0;
		}

		const containerTop = dropdownContainer.getBoundingClientRect().top;
		let activeOffset = 0;
		const stickyHeaders = dropdownContainer.querySelectorAll('[data-dropdown-header]');
		stickyHeaders.forEach((header) => {
			const rect = (header as HTMLElement).getBoundingClientRect();
			const overlapsTopEdge = rect.top <= containerTop + 1 && rect.bottom > containerTop + 1;
			if (overlapsTopEdge) {
				activeOffset = Math.max(activeOffset, rect.bottom - containerTop);
			}
		});
		return activeOffset;
	}

	function updateTopOverflowLabel() {
		if (!dropdownOpen || !dropdownContainer || !topOverflowLabel) {
			topOverflowLabelOpacity = 0;
			topOverflowLabelOffset = 0;
			return;
		}

		const activeStickyHeaderOffset = getActiveStickyHeaderOffset();
		const firstOption = dropdownContainer.querySelector(
			'[data-dropdown-option]'
		) as HTMLElement | null;
		const containerTop = dropdownContainer.getBoundingClientRect().top;
		const visibleTop = containerTop + activeStickyHeaderOffset;
		const shouldShowByScroll = dropdownContainer.scrollTop > TOP_OVERFLOW_LABEL_THRESHOLD;
		const firstOptionRect = firstOption?.getBoundingClientRect();
		const firstOptionVisibleHeight =
			firstOptionRect && firstOption
				? clamp(firstOptionRect.bottom - visibleTop, 0, firstOption.offsetHeight)
				: 0;

		if (!shouldShowByScroll) {
			topOverflowLabelOpacity = 0;
			return;
		}

		if (firstOptionVisibleHeight <= TOP_OVERFLOW_LABEL_FADE_START_VISIBLE_PX) {
			topOverflowLabelOpacity = 1;
		} else {
			topOverflowLabelOpacity = clamp(
				1 -
					(firstOptionVisibleHeight - TOP_OVERFLOW_LABEL_FADE_START_VISIBLE_PX) /
						TOP_OVERFLOW_LABEL_FADE_RANGE_PX,
				0,
				1
			);
		}

		topOverflowLabelOffset = activeStickyHeaderOffset;
	}

	function scrollSelectedOptionIntoView() {
		const currentNode = optionNodes[selectedOption];
		if (!currentNode || !dropdownContainer) {
			return;
		}

		const dropdownRect = dropdownContainer.getBoundingClientRect();
		const nodeRect = currentNode.getBoundingClientRect();
		const stickyHeaderHeight = getStickyHeaderHeight(optionHeaders[selectedOption]);
		const nodeTop = nodeRect.top - dropdownRect.top + dropdownContainer.scrollTop;
		const nodeBottom = nodeTop + nodeRect.height;
		const availableHeight = dropdownContainer.clientHeight - stickyHeaderHeight;
		const maxScrollTop = Math.max(
			0,
			dropdownContainer.scrollHeight - dropdownContainer.clientHeight
		);
		let nextScrollTop: number;

		if (selectedOptionScrollAlign === 'center') {
			const alignOffset =
				stickyHeaderHeight + Math.max(16, (availableHeight - nodeRect.height) / 2);
			nextScrollTop = clamp(nodeTop - alignOffset, 0, maxScrollTop);
		} else if (selectedOptionScrollAlign === 'keep-visible') {
			const minVisibleScrollTop = nodeBottom - dropdownContainer.clientHeight;
			const maxVisibleScrollTop = nodeTop - stickyHeaderHeight;

			nextScrollTop = clamp(minVisibleScrollTop, 0, maxScrollTop);
			if (nextScrollTop > maxVisibleScrollTop) {
				nextScrollTop = clamp(maxVisibleScrollTop, 0, maxScrollTop);
			}
		} else {
			nextScrollTop = clamp(nodeTop - stickyHeaderHeight, 0, maxScrollTop);
		}

		dropdownContainer.scrollTo({
			top: nextScrollTop,
			behavior: 'instant'
		});
		updateTopOverflowLabel();
	}

	function handleWindowClick(event: MouseEvent) {
		if (!dropdownOpen || !dropdownRoot) {
			return;
		}

		if (!event.composedPath().includes(dropdownRoot)) {
			dropdownOpen = false;
		}
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			dropdownOpen = false;
		}
	}

	afterUpdate(async () => {
		const shouldScrollSelectedOption =
			dropdownOpen && (!previousDropdownOpen || previousSelectedOption !== selectedOption);

		previousDropdownOpen = dropdownOpen;
		previousSelectedOption = selectedOption;

		if (shouldScrollSelectedOption) {
			await tick();
			scrollSelectedOptionIntoView();
			return;
		}

		updateTopOverflowLabel();
	});
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleWindowKeydown} />

<div class="relative w-full min-w-0 grow" bind:this={dropdownRoot}>
	<button
		id="model"
		name="model"
		class="focus:ring-primary-500 focus:border-primary-500 dark:focus:ring-primary-500 dark:focus:border-primary-500 flex h-10 w-full items-center overflow-hidden rounded-lg border border-gray-300 bg-gray-50 p-2.5 text-sm text-gray-900 focus:ring-3 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400"
		type="button"
		aria-expanded={dropdownOpen}
		aria-haspopup="listbox"
		{disabled}
		onclick={() => {
			if (!disabled) {
				dropdownOpen = !dropdownOpen;
			}
		}}
	>
		<span class="mr-2 grow truncate text-left">{placeholder}</span>
		<ChevronDownOutline class="h-6 w-6 shrink-0" />
	</button>

	{#if dropdownOpen}
		<div
			class="{width} absolute top-full left-0 z-10 mt-2 flex flex-col rounded-lg border border-gray-300 bg-white shadow-md dark:border-gray-600 dark:bg-gray-700"
		>
			<div class="relative rounded-lg">
				{#if topOverflowLabel}
					<div
						aria-hidden="true"
						class="pointer-events-none absolute inset-x-0 z-60 flex justify-center px-3 transition-opacity duration-150"
						style={`top: ${topOverflowLabelOffset}px; opacity: ${topOverflowLabelOpacity};`}
					>
						<div
							class="mt-2 flex items-center gap-1 rounded-full border border-gray-200 bg-white/95 px-2.5 py-1 text-xs font-medium text-gray-500 shadow-sm dark:border-gray-500 dark:bg-gray-700/95 dark:text-gray-300"
						>
							<ArrowUpOutline class="h-3.5 w-3.5 shrink-0" />
							{topOverflowLabel}
						</div>
					</div>
				{/if}
				<div
					class="overflow-y-auto overscroll-contain {footer
						? 'rounded-t-lg'
						: 'rounded-lg'} relative max-h-80 grow py-0"
					bind:this={dropdownContainer}
					onscroll={updateTopOverflowLabel}
				>
					<slot />
				</div>
				<slot name="footer" />
			</div>
		</div>
	{/if}
</div>
