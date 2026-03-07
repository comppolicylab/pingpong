<script lang="ts">
	import {
		ChevronDownOutline,
		ChevronLeftOutline,
		ChevronRightOutline,
		ChevronUpOutline,
		CloseOutline,
		ExpandOutline,
		FileCopyOutline,
		MinusOutline,
		PlusOutline,
		RefreshOutline
	} from 'flowbite-svelte-icons';
	import { onMount, tick } from 'svelte';
	import { copy } from 'svelte-copy';
	import { getMermaid } from '$lib/mermaid';
	import { happyToast, sadToast } from '$lib/toast';
	import { Tooltip } from 'flowbite-svelte';

	export let source: string;

	type ViewMode = 'preview' | 'modal';
	type ViewState = {
		scale: number;
		x: number;
		y: number;
	};
	type TouchState = {
		lastX: number;
		lastY: number;
		lastDistance: number | null;
	};

	let previewContainer: HTMLDivElement;
	let modalContainer: HTMLDivElement;
	let previewViewport: HTMLDivElement;
	let modalViewport: HTMLDivElement;
	let modalDialog: HTMLDivElement;
	let openButton: HTMLButtonElement;
	let closeButton: HTMLButtonElement;
	let modalOpen = false;
	let loading = true;
	let modalLoading = false;
	let error = '';
	let previewView: ViewState = { scale: 1, x: 0, y: 0 };
	let modalView: ViewState = { scale: 1, x: 0, y: 0 };
	let previewTouchState: TouchState = { lastX: 0, lastY: 0, lastDistance: null };
	let modalTouchState: TouchState = { lastX: 0, lastY: 0, lastDistance: null };
	let previewGesturesEnabled = false;
	let lastFocusedElement: HTMLElement | null = null;
	let renderedSource = source;

	const diagramId = `mermaid-${Math.random().toString(36).slice(2)}`;
	const ZOOM_STEP = 0.15;
	const PAN_STEP = 60;
	const MIN_SCALE = 0.05;
	const MAX_SCALE = 2.5;
	const controlPanelClass = 'absolute right-3 bottom-3 z-10 grid grid-cols-3 gap-1';
	const controlButtonBaseClass =
		'inline-flex h-10 w-10 items-center justify-center rounded-md border border-gray-200 bg-white/95 p-2 text-gray-800 transition hover:border-gray-300 hover:bg-gray-100 hover:text-gray-950';
	const controlPositionClass: Record<string, string> = {
		up: 'col-start-2 row-start-1',
		'zoom-in': 'col-start-3 row-start-1',
		left: 'col-start-1 row-start-2',
		reset: 'col-start-2 row-start-2',
		right: 'col-start-3 row-start-2',
		down: 'col-start-2 row-start-3',
		'zoom-out': 'col-start-3 row-start-3'
	};
	const diagramCanvasClass =
		'absolute top-0 left-0 w-max max-w-none will-change-transform [&_svg]:block [&_svg]:h-auto [&_svg]:max-w-none [&_.label]:font-inherit';

	const controls = [
		{
			key: 'zoom-in',
			label: 'Zoom in',
			icon: PlusOutline,
			action: (view: ViewMode) => zoom(view, ZOOM_STEP)
		},
		{
			key: 'zoom-out',
			label: 'Zoom out',
			icon: MinusOutline,
			action: (view: ViewMode) => zoom(view, -ZOOM_STEP)
		},
		{
			key: 'reset',
			label: 'Reset view',
			icon: RefreshOutline,
			action: (view: ViewMode) => resetView(view)
		},
		{
			key: 'up',
			label: 'Pan up',
			icon: ChevronUpOutline,
			action: (view: ViewMode) => pan(view, 0, -PAN_STEP)
		},
		{
			key: 'down',
			label: 'Pan down',
			icon: ChevronDownOutline,
			action: (view: ViewMode) => pan(view, 0, PAN_STEP)
		},
		{
			key: 'left',
			label: 'Pan left',
			icon: ChevronLeftOutline,
			action: (view: ViewMode) => pan(view, -PAN_STEP, 0)
		},
		{
			key: 'right',
			label: 'Pan right',
			icon: ChevronRightOutline,
			action: (view: ViewMode) => pan(view, PAN_STEP, 0)
		}
	];

	const clampScale = (value: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));

	const getContainer = (view: ViewMode) => (view === 'preview' ? previewContainer : modalContainer);

	const getViewport = (view: ViewMode) => (view === 'preview' ? previewViewport : modalViewport);

	const getViewState = (view: ViewMode) => (view === 'preview' ? previewView : modalView);

	const getTouchState = (view: ViewMode) =>
		view === 'preview' ? previewTouchState : modalTouchState;

	const gesturesEnabled = (view: ViewMode) => view === 'modal' || previewGesturesEnabled;

	const setViewState = (view: ViewMode, next: ViewState) => {
		if (view === 'preview') {
			previewView = next;
		} else {
			modalView = next;
		}
	};

	const setTouchState = (view: ViewMode, next: TouchState) => {
		if (view === 'preview') {
			previewTouchState = next;
		} else {
			modalTouchState = next;
		}
	};

	const togglePreviewGestures = () => {
		previewGesturesEnabled = !previewGesturesEnabled;
		if (!previewGesturesEnabled) {
			setTouchState('preview', { lastX: 0, lastY: 0, lastDistance: null });
		}
	};

	const getDiagramMetrics = (container: HTMLDivElement | undefined) => {
		if (!container) {
			return null;
		}

		const svg = container.querySelector('svg');
		if (!(svg instanceof SVGSVGElement)) {
			return null;
		}

		let width = Number(container.dataset.baseWidth);
		let height = Number(container.dataset.baseHeight);

		if (!width || !height) {
			const viewBox = svg.viewBox.baseVal;
			width = viewBox?.width || svg.getBBox().width || svg.clientWidth;
			height = viewBox?.height || svg.getBBox().height || svg.clientHeight;
			if (!width || !height) {
				return null;
			}

			container.dataset.baseWidth = `${width}`;
			container.dataset.baseHeight = `${height}`;
		}

		return { svg, width, height };
	};

	const applyTransform = (view: ViewMode) => {
		const container = getContainer(view);
		const metrics = getDiagramMetrics(container);
		if (!container || !metrics) {
			return;
		}

		const state = getViewState(view);
		const renderedWidth = metrics.width * state.scale;
		const renderedHeight = metrics.height * state.scale;
		container.style.width = `${renderedWidth}px`;
		container.style.height = `${renderedHeight}px`;
		container.style.transform = `translate(${state.x}px, ${state.y}px)`;
		container.style.transformOrigin = 'top left';
		metrics.svg.setAttribute('width', `${renderedWidth}`);
		metrics.svg.setAttribute('height', `${renderedHeight}`);
		metrics.svg.style.width = `${renderedWidth}px`;
		metrics.svg.style.height = `${renderedHeight}px`;
		metrics.svg.style.maxWidth = 'none';
	};

	const fitView = (view: ViewMode) => {
		const container = getContainer(view);
		const viewport = getViewport(view);
		const metrics = getDiagramMetrics(container);
		if (!container || !viewport || !metrics) {
			return;
		}

		const padding = 32;
		const scale = clampScale(
			Math.min(
				(viewport.clientWidth - padding) / metrics.width,
				(viewport.clientHeight - padding) / metrics.height,
				1
			)
		);

		setViewState(view, {
			scale,
			x: (viewport.clientWidth - metrics.width * scale) / 2,
			y: (viewport.clientHeight - metrics.height * scale) / 2
		});
		applyTransform(view);
	};

	const setScaleAtPoint = (view: ViewMode, nextScale: number, anchorX: number, anchorY: number) => {
		const container = getContainer(view);
		const metrics = getDiagramMetrics(container);
		const state = getViewState(view);
		const scale = clampScale(nextScale);
		if (!metrics || scale === state.scale) {
			setViewState(view, { ...state, scale });
			applyTransform(view);
			return;
		}

		const oldWidth = metrics.width * state.scale;
		const oldHeight = metrics.height * state.scale;
		const focusX = oldWidth ? (anchorX - state.x) / oldWidth : 0.5;
		const focusY = oldHeight ? (anchorY - state.y) / oldHeight : 0.5;
		const newWidth = metrics.width * scale;
		const newHeight = metrics.height * scale;

		setViewState(view, {
			scale,
			x: anchorX - focusX * newWidth,
			y: anchorY - focusY * newHeight
		});
		applyTransform(view);
	};

	const zoom = (view: ViewMode, delta: number) => {
		const viewport = getViewport(view);
		const state = getViewState(view);
		const scale = clampScale(state.scale + delta);
		if (!viewport) {
			setScaleAtPoint(view, scale, 0, 0);
			return;
		}

		setScaleAtPoint(view, scale, viewport.clientWidth / 2, viewport.clientHeight / 2);
	};

	const pan = (view: ViewMode, dx: number, dy: number) => {
		const state = getViewState(view);
		setViewState(view, { ...state, x: state.x + dx, y: state.y + dy });
		applyTransform(view);
	};

	const resetView = (view: ViewMode) => {
		fitView(view);
	};

	const getRelativePoint = (view: ViewMode, clientX: number, clientY: number) => {
		const viewport = getViewport(view);
		if (!viewport) {
			return null;
		}

		const rect = viewport.getBoundingClientRect();
		return {
			x: clientX - rect.left,
			y: clientY - rect.top
		};
	};

	const getTouchMetrics = (view: ViewMode, touches: TouchList) => {
		if (touches.length < 2) {
			return null;
		}

		const first = getRelativePoint(view, touches[0].clientX, touches[0].clientY);
		const second = getRelativePoint(view, touches[1].clientX, touches[1].clientY);
		if (!first || !second) {
			return null;
		}

		const dx = second.x - first.x;
		const dy = second.y - first.y;
		return {
			x: (first.x + second.x) / 2,
			y: (first.y + second.y) / 2,
			distance: Math.hypot(dx, dy)
		};
	};

	const handleWheel = (view: ViewMode, event: WheelEvent) => {
		if (!gesturesEnabled(view)) {
			return;
		}

		event.preventDefault();

		const point = getRelativePoint(view, event.clientX, event.clientY);
		if (point && (event.ctrlKey || event.metaKey)) {
			const nextScale = clampScale(getViewState(view).scale * Math.exp(-event.deltaY * 0.003));
			setScaleAtPoint(view, nextScale, point.x, point.y);
			return;
		}

		pan(view, -event.deltaX, -event.deltaY);
	};

	const handleTouchStart = (view: ViewMode, event: TouchEvent) => {
		if (!gesturesEnabled(view)) {
			return;
		}

		if (event.touches.length === 1) {
			const point = getRelativePoint(view, event.touches[0].clientX, event.touches[0].clientY);
			if (!point) {
				return;
			}

			setTouchState(view, { lastX: point.x, lastY: point.y, lastDistance: null });
			return;
		}

		const metrics = getTouchMetrics(view, event.touches);
		if (!metrics) {
			return;
		}

		event.preventDefault();
		setTouchState(view, { lastX: metrics.x, lastY: metrics.y, lastDistance: metrics.distance });
	};

	const handleTouchMove = (view: ViewMode, event: TouchEvent) => {
		if (!gesturesEnabled(view)) {
			return;
		}

		if (event.touches.length === 1) {
			const point = getRelativePoint(view, event.touches[0].clientX, event.touches[0].clientY);
			if (!point) {
				return;
			}

			event.preventDefault();
			const touchState = getTouchState(view);
			pan(view, point.x - touchState.lastX, point.y - touchState.lastY);
			setTouchState(view, { lastX: point.x, lastY: point.y, lastDistance: null });
			return;
		}

		const metrics = getTouchMetrics(view, event.touches);
		if (!metrics) {
			return;
		}

		event.preventDefault();
		const touchState = getTouchState(view);
		if (touchState.lastDistance) {
			pan(view, metrics.x - touchState.lastX, metrics.y - touchState.lastY);
			const nextScale = clampScale(
				getViewState(view).scale * (metrics.distance / touchState.lastDistance)
			);
			setScaleAtPoint(view, nextScale, metrics.x, metrics.y);
		}

		setTouchState(view, {
			lastX: metrics.x,
			lastY: metrics.y,
			lastDistance: metrics.distance
		});
	};

	const handleTouchEnd = (view: ViewMode, event: TouchEvent) => {
		if (!gesturesEnabled(view)) {
			return;
		}

		if (event.touches.length === 1) {
			const point = getRelativePoint(view, event.touches[0].clientX, event.touches[0].clientY);
			if (!point) {
				return;
			}

			setTouchState(view, { lastX: point.x, lastY: point.y, lastDistance: null });
			return;
		}

		setTouchState(view, { lastX: 0, lastY: 0, lastDistance: null });
	};

	const renderInto = async (container: HTMLDivElement | undefined, view: ViewMode) => {
		if (!container) {
			return;
		}

		const mermaid = await getMermaid();
		const { svg, bindFunctions } = await mermaid.render(`${diagramId}-${view}`, source);
		delete container.dataset.baseWidth;
		delete container.dataset.baseHeight;
		container.innerHTML = svg;
		bindFunctions?.(container);

		const metrics = getDiagramMetrics(container);
		if (metrics) {
			metrics.svg.setAttribute('width', `${metrics.width}`);
			metrics.svg.setAttribute('height', `${metrics.height}`);
			metrics.svg.style.width = `${metrics.width}px`;
			metrics.svg.style.height = `${metrics.height}px`;
			metrics.svg.style.maxWidth = 'none';
		}

		fitView(view);
	};

	const renderPreview = async () => {
		loading = true;
		error = '';

		try {
			await tick();
			await renderInto(previewContainer, 'preview');
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to render Mermaid diagram.';
			sadToast('Could not render Mermaid diagram.');
		} finally {
			loading = false;
		}
	};

	const renderModalDiagram = async () => {
		modalLoading = true;
		try {
			await renderInto(modalContainer, 'modal');
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to render Mermaid diagram.';
		} finally {
			modalLoading = false;
		}
	};

	const handleCopy = () => {
		happyToast('Mermaid code copied to clipboard', 2000);
	};

	const getModalFocusableElements = () => {
		if (!modalDialog) {
			return [];
		}

		return Array.from(
			modalDialog.querySelectorAll<HTMLElement>(
				'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
			)
		).filter(
			(element) => !element.hasAttribute('disabled') && !element.getAttribute('aria-hidden')
		);
	};

	const openModal = () => {
		lastFocusedElement =
			document.activeElement instanceof HTMLElement ? document.activeElement : openButton;
		modalOpen = true;
	};

	const closeModal = async () => {
		modalOpen = false;
		setTouchState('modal', { lastX: 0, lastY: 0, lastDistance: null });
		await tick();
		lastFocusedElement?.focus();
		lastFocusedElement = null;
	};

	const handleModalKeydown = (event: KeyboardEvent) => {
		if (event.key === 'Escape') {
			event.preventDefault();
			void closeModal();
			return;
		}

		if (event.key !== 'Tab') {
			return;
		}

		const focusableElements = getModalFocusableElements();
		if (!focusableElements.length) {
			event.preventDefault();
			closeButton?.focus();
			return;
		}

		const firstElement = focusableElements[0];
		const lastElement = focusableElements[focusableElements.length - 1];
		const activeElement = document.activeElement;

		if (event.shiftKey) {
			if (activeElement === firstElement || !modalDialog.contains(activeElement)) {
				event.preventDefault();
				lastElement.focus();
			}
			return;
		}

		if (activeElement === lastElement) {
			event.preventDefault();
			firstElement.focus();
		}
	};

	onMount(() => {
		const handleResize = () => {
			resetView('preview');
			if (modalOpen) {
				resetView('modal');
			}
		};

		window.addEventListener('resize', handleResize);
		void renderPreview();

		return () => {
			window.removeEventListener('resize', handleResize);
		};
	});

	$: if (source !== renderedSource) {
		renderedSource = source;
		resetView('preview');
		void (async () => {
			await renderPreview();
			if (modalOpen) {
				await tick();
				await renderModalDiagram();
			}
		})();
	}

	$: if (modalOpen) {
		void (async () => {
			await tick();
			await renderModalDiagram();
			closeButton?.focus();
		})();
	}
</script>

<div
	class="mermaid-block not-prose relative mb-4 max-w-full overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm"
>
	<div
		class="flex items-center justify-between gap-3 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white px-3 py-2"
	>
		<div class="text-xs font-semibold tracking-[0.18em] text-gray-500 uppercase">Mermaid</div>
		<div class="flex items-center gap-1">
			<button
				bind:this={openButton}
				class="rounded-md border border-gray-200 p-2 text-gray-600 transition hover:border-gray-300 hover:bg-gray-100 hover:text-gray-900"
				aria-label="Open Mermaid diagram in a larger view"
				onclick={openModal}
			>
				<ExpandOutline class="h-4 w-4" />
			</button>
			<button
				class="rounded-md border border-gray-200 p-2 text-gray-600 transition hover:border-gray-300 hover:bg-gray-100 hover:text-gray-900"
				aria-label="Copy Mermaid code"
				onclick={() => {}}
				use:copy={{ text: source, onCopy: handleCopy }}
			>
				<FileCopyOutline class="h-4 w-4" />
			</button>
		</div>
	</div>

	<div class="relative max-w-full min-w-0 overflow-hidden bg-white px-3 py-4">
		<div
			bind:this={previewViewport}
			class="relative h-[26rem] overflow-hidden rounded-lg border border-gray-100 bg-gray-50/40"
			class:touch-none={previewGesturesEnabled}
			role="application"
			aria-label="Interactive Mermaid diagram preview"
			onwheel={(event) => handleWheel('preview', event)}
			ontouchstart={(event) => handleTouchStart('preview', event)}
			ontouchmove={(event) => handleTouchMove('preview', event)}
			ontouchend={(event) => handleTouchEnd('preview', event)}
			ontouchcancel={(event) => handleTouchEnd('preview', event)}
		>
			{#if !loading && !error}
				<div class={controlPanelClass}>
					<button
						class:border-emerald-300={previewGesturesEnabled}
						class:bg-emerald-50={previewGesturesEnabled}
						class:text-emerald-700={previewGesturesEnabled}
						class={`${controlButtonBaseClass} relative col-start-1 row-start-3`}
						aria-label={previewGesturesEnabled
							? 'Disable preview gestures'
							: 'Enable preview gestures'}
						aria-pressed={previewGesturesEnabled}
						onclick={togglePreviewGestures}
					>
						<span class="text-[9px] font-semibold tracking-[0.18em]">PAN</span>
						{#if !previewGesturesEnabled}
							<span
								aria-hidden="true"
								class="absolute top-1/2 left-1/2 h-0.5 w-7 -translate-x-1/2 -translate-y-1/2 -rotate-45 rounded-full bg-current"
							></span>
						{/if}
					</button>
					<Tooltip class="font-normal" arrow={false}>
						{#if previewGesturesEnabled}
							Disable touch gestures
						{:else}
							Enable touch gestures
						{/if}
					</Tooltip>
					{#each controls as control (control.key)}
						<button
							class={`${controlButtonBaseClass} ${controlPositionClass[control.key]}`}
							aria-label={control.label}
							onclick={() => control.action('preview')}
						>
							<svelte:component this={control.icon} class="h-5 w-5" />
						</button>
					{/each}
				</div>
			{/if}
			<div bind:this={previewContainer} class:hidden={!!error} class={diagramCanvasClass}></div>
			{#if loading}
				<div
					class="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500"
				>
					Rendering diagram...
				</div>
			{:else if error}
				<div class="space-y-3">
					<div class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
						{error}
					</div>
					<pre
						class="overflow-x-auto rounded-lg bg-gray-950 p-4 text-xs leading-6 whitespace-pre-wrap text-gray-100"><code
							>{source}</code
						></pre>
				</div>
			{/if}
		</div>
	</div>
</div>

{#if modalOpen}
	<div
		bind:this={modalDialog}
		class="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/20 p-6"
		role="dialog"
		aria-modal="true"
		aria-label="Mermaid diagram"
		tabindex="-1"
		onclick={(event) => {
			if (event.target === event.currentTarget) {
				void closeModal();
			}
		}}
		onkeydown={handleModalKeydown}
	>
		<div class="h-full max-h-[92vh] w-full max-w-[96vw]">
			<div
				bind:this={modalViewport}
				class="relative h-full touch-none overflow-hidden rounded-lg border border-gray-200 bg-white"
				role="application"
				aria-label="Interactive Mermaid diagram"
				onwheel={(event) => handleWheel('modal', event)}
				ontouchstart={(event) => handleTouchStart('modal', event)}
				ontouchmove={(event) => handleTouchMove('modal', event)}
				ontouchend={(event) => handleTouchEnd('modal', event)}
				ontouchcancel={(event) => handleTouchEnd('modal', event)}
			>
				<button
					bind:this={closeButton}
					class="absolute top-3 right-3 z-20 rounded-md border border-gray-200 bg-white p-2 text-gray-600 transition hover:border-gray-300 hover:bg-gray-100 hover:text-gray-900"
					aria-label="Close diagram"
					onclick={() => void closeModal()}
				>
					<CloseOutline class="h-6 w-6" />
				</button>
				<div class={controlPanelClass}>
					{#each controls as control (control.key)}
						<button
							class={`${controlButtonBaseClass} ${controlPositionClass[control.key]}`}
							aria-label={control.label}
							onclick={() => control.action('modal')}
						>
							<svelte:component this={control.icon} class="h-5 w-5" />
						</button>
					{/each}
				</div>
				<div
					bind:this={modalContainer}
					class:hidden={modalLoading}
					class={diagramCanvasClass}
				></div>
				{#if modalLoading}
					<div
						class="m-4 rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500"
					>
						Rendering diagram...
					</div>
				{/if}
			</div>
		</div>
	</div>
{/if}
