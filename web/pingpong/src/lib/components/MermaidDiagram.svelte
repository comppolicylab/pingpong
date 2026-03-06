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
	import { happyToast, sadToast } from '$lib/toast';

	export let source: string;

	type ViewMode = 'preview' | 'modal';
	type ViewState = {
		scale: number;
		x: number;
		y: number;
	};

	let previewContainer: HTMLDivElement;
	let modalContainer: HTMLDivElement;
	let previewViewport: HTMLDivElement;
	let modalViewport: HTMLDivElement;
	let modalOpen = false;
	let loading = true;
	let error = '';
	let previewView: ViewState = { scale: 1, x: 0, y: 0 };
	let modalView: ViewState = { scale: 1, x: 0, y: 0 };

	const diagramId = `mermaid-${Math.random().toString(36).slice(2)}`;
	let mermaidPromise: Promise<typeof import('mermaid').default> | null = null;
	const ZOOM_STEP = 0.15;
	const PAN_STEP = 60;
	const MIN_SCALE = 0.5;
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
		'min-w-max [&_svg]:block [&_svg]:h-auto [&_svg]:max-w-none [&_.label]:font-inherit';

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

	const setViewState = (view: ViewMode, next: ViewState) => {
		if (view === 'preview') {
			previewView = next;
		} else {
			modalView = next;
		}
	};

	const applyTransform = (view: ViewMode) => {
		const container = getContainer(view);
		if (!container) {
			return;
		}

		const state = getViewState(view);
		container.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
		container.style.transformOrigin = 'top left';
	};

	const fitView = (view: ViewMode) => {
		const container = getContainer(view);
		const viewport = getViewport(view);
		const svg = container?.querySelector('svg');
		if (!container || !viewport || !(svg instanceof SVGSVGElement)) {
			return;
		}

		const viewBox = svg.viewBox.baseVal;
		const width = viewBox?.width || svg.getBBox().width || svg.clientWidth;
		const height = viewBox?.height || svg.getBBox().height || svg.clientHeight;
		if (!width || !height) {
			return;
		}

		const padding = 32;
		const scale = clampScale(
			Math.min(
				(viewport.clientWidth - padding) / width,
				(viewport.clientHeight - padding) / height,
				1
			)
		);

		setViewState(view, {
			scale,
			x: (viewport.clientWidth - width * scale) / 2,
			y: (viewport.clientHeight - height * scale) / 2
		});
		applyTransform(view);
	};

	const zoom = (view: ViewMode, delta: number) => {
		const state = getViewState(view);
		setViewState(view, { ...state, scale: clampScale(state.scale + delta) });
		applyTransform(view);
	};

	const pan = (view: ViewMode, dx: number, dy: number) => {
		const state = getViewState(view);
		setViewState(view, { ...state, x: state.x + dx, y: state.y + dy });
		applyTransform(view);
	};

	const resetView = (view: ViewMode) => {
		fitView(view);
	};

	const getMermaid = async () => {
		if (!mermaidPromise) {
			mermaidPromise = import('mermaid').then(({ default: mermaid }) => {
				mermaid.initialize({
					startOnLoad: false,
					theme: 'neutral',
					securityLevel: 'strict'
				});
				return mermaid;
			});
		}

		return mermaidPromise;
	};

	const renderInto = async (container: HTMLDivElement | undefined, suffix: string) => {
		if (!container) {
			return;
		}

		const mermaid = await getMermaid();
		const { svg, bindFunctions } = await mermaid.render(`${diagramId}-${suffix}`, source);
		container.innerHTML = svg;
		bindFunctions?.(container);
		fitView(suffix === 'preview' ? 'preview' : 'modal');
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
		try {
			await renderInto(modalContainer, 'modal');
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to render Mermaid diagram.';
		}
	};

	const handleCopy = () => {
		happyToast('Mermaid code copied to clipboard', 2000);
	};

	const openModal = () => {
		resetView('modal');
		modalOpen = true;
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

	$: if (modalOpen) {
		tick().then(() => {
			void renderModalDiagram();
		});
	}
</script>

<div
	class="mermaid-block not-prose relative mb-4 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm"
>
	<div
		class="flex items-center justify-between gap-3 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white px-3 py-2"
	>
		<div class="text-xs font-semibold tracking-[0.18em] text-gray-500 uppercase">Mermaid</div>
		<div class="flex items-center gap-1">
			<button
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

	<div class="relative overflow-hidden bg-white px-3 py-4">
		<div
			bind:this={previewViewport}
			class="relative h-[26rem] overflow-hidden rounded-lg border border-gray-100 bg-gray-50/40"
		>
			{#if !loading && !error}
				<div class={controlPanelClass}>
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
		class="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/20 p-6"
		role="dialog"
		aria-modal="true"
		aria-label="Mermaid diagram"
		tabindex="-1"
		onclick={(event) => {
			if (event.target === event.currentTarget) {
				modalOpen = false;
			}
		}}
		onkeydown={(event) => {
			if (event.key === 'Escape') {
				modalOpen = false;
			}
		}}
	>
		<div class="h-full max-h-[92vh] w-full max-w-[96vw]">
			<div
				bind:this={modalViewport}
				class="relative h-full overflow-hidden rounded-lg border border-gray-200 bg-white"
			>
				<button
					class="absolute top-3 right-3 z-20 rounded-md border border-gray-200 bg-white p-2 text-gray-600 transition hover:border-gray-300 hover:bg-gray-100 hover:text-gray-900"
					aria-label="Close diagram"
					onclick={() => (modalOpen = false)}
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
				<div bind:this={modalContainer} class={diagramCanvasClass}></div>
			</div>
		</div>
	</div>
{/if}
