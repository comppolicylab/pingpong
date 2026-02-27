<script lang="ts">
	import { FileCodeOutline, ImageOutline, PaperClipOutline } from 'flowbite-svelte-icons';

	export let visible = false;
	export let title = 'Drop files to upload';
	export let subtitle = 'Drop anywhere in this conversation window';
</script>

{#if visible}
	<div
		class="pointer-events-none absolute inset-0 z-70 flex items-center justify-center bg-white/70 backdrop-blur-sm"
	>
		<div class="flex flex-col items-center gap-4 text-center">
			<div class="relative flex h-24 w-32 items-center justify-center">
				<div
					class="petal absolute flex h-14 w-14 items-center justify-center rounded-xl bg-amber-100 text-amber-600"
					style="--petal-x: -38px; --petal-y: -6px; --petal-rotate: -15deg; animation-delay: 0ms;"
				>
					<PaperClipOutline class="h-7 w-7" />
				</div>
				<div
					class="petal absolute flex h-14 w-14 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600"
					style="--petal-x: 0px; --petal-y: -18px; --petal-rotate: 0deg; animation-delay: 60ms;"
				>
					<FileCodeOutline class="h-7 w-7" />
				</div>
				<div
					class="petal absolute flex h-14 w-14 items-center justify-center rounded-xl bg-indigo-100 text-indigo-500"
					style="--petal-x: 38px; --petal-y: -6px; --petal-rotate: 15deg; animation-delay: 120ms;"
				>
					<ImageOutline class="h-7 w-7" />
				</div>
			</div>
			<div class="flex flex-col gap-1">
				<p
					class="petal-text text-2xl leading-tight font-semibold text-gray-900 md:text-3xl"
					style="animation-delay: 100ms;"
				>
					{title}
				</p>
				<p class="petal-text text-sm text-gray-500 md:text-base" style="animation-delay: 160ms;">
					{subtitle}
				</p>
			</div>
		</div>
	</div>
{/if}

<style>
	.petal {
		animation: petal-in 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both;
	}

	.petal-text {
		animation: fade-up 0.3s ease-out both;
	}

	@keyframes petal-in {
		from {
			opacity: 0;
			transform: translate(0, 12px) rotate(0deg) scale(0.5);
		}
		to {
			opacity: 1;
			transform: translate(var(--petal-x), var(--petal-y)) rotate(var(--petal-rotate)) scale(1);
		}
	}

	@keyframes fade-up {
		from {
			opacity: 0;
			transform: translateY(8px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
</style>
