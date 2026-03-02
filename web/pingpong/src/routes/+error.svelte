<script lang="ts">
	import { page } from '$app/stores';
	import { cubicOut } from 'svelte/easing';
	import { slide } from 'svelte/transition';

	type RouteError = App.Error & { detail?: string };
	let showTechnicalDetails = false;
	$: status = $page.status || 500;
	$: routeError = ($page.error ?? {}) as RouteError;
	$: rawMessage = (
		routeError?.message ||
		routeError?.detail ||
		'An unexpected error occurred.'
	).trim();
	$: isForbidden = status === 403;
	$: isNotFound = status === 404;
	$: isUnauthorized = status === 401;

	$: title = isForbidden
		? "You can't view this page"
		: isNotFound
			? "This page doesn't exist"
			: status >= 500
				? 'PingPong ran into a server error'
				: 'We could not load this page';

	$: description = isForbidden
		? "Your account doesn't have access to this page. Check that you are signed in with the correct account, and contact your moderator or administrator if you think this is a mistake."
		: isNotFound
			? "The page you're looking for doesn't exist. It may have been removed, or you may have followed a broken link."
			: isUnauthorized
				? 'Your session may have expired. Sign in again and try one more time.'
				: status >= 500
					? 'This is likely temporary. Refresh the page in a moment, or return to the dashboard.'
					: 'An unexpected error occurred while loading this page.';
</script>

<div
	class="relative box-border flex h-full min-h-full w-full items-center justify-center overflow-hidden bg-[#201e45] p-4 md:p-6"
>
	<div class="relative w-full max-w-208">
		<div
			class="pointer-events-none absolute -left-15 -top-20 h-75 w-75 rounded-full opacity-[0.5] [background:radial-gradient(circle,#6d28d9_0%,transparent_70%)] filter-[blur(120px)]"
		></div>
		<div
			class="pointer-events-none absolute -bottom-17.5 -right-12.5 h-70 w-70 rounded-full opacity-[0.5] [background:radial-gradient(circle,#2563eb_0%,transparent_70%)] filter-[blur(120px)]"
		></div>
		<div
			class="pointer-events-none absolute -bottom-22.5 left-[30%] h-70 w-70 rounded-full opacity-[0.3] [background:radial-gradient(circle,#db2777_0%,transparent_70%)] filter-[blur(120px)]"
		></div>
		<section
			class="relative z-1 w-full rounded-[1.75rem] border border-white/30 bg-white/95 shadow-[0_1px_1px_rgba(15,23,42,0.04),0_24px_50px_-24px_rgba(15,23,42,0.24)] backdrop-blur-[18px] backdrop-saturate-160"
		>
			<div class="mx-auto w-full max-w-312 px-6 py-10 md:px-12 md:pb-12 md:pt-[3.2rem]">
				<div class="grid grid-cols-1 gap-8">
					<div>
						<h1
							class="m-0 max-w-[24ch] text-[clamp(1.35rem,2.5vw,2.1rem)] font-semibold leading-[1.15] tracking-[-0.02em] text-slate-900"
						>
							{title}
						</h1>
						<p class="mb-0 mt-4 max-w-[62ch] text-base leading-[1.7] text-slate-700">
							{description}
						</p>
					</div>
				</div>

				<div class="mt-7 border-t border-slate-900/10 pt-4">
					<button
						type="button"
						class="inline-flex cursor-pointer items-center gap-2 border-none bg-transparent p-0 text-[0.85rem] font-semibold text-slate-700"
						aria-expanded={showTechnicalDetails}
						aria-controls="error-details-panel"
						on:click={() => (showTechnicalDetails = !showTechnicalDetails)}
					>
						<span>Technical details</span>
						<span
							class={`inline-flex h-[1.1rem] w-[1.1rem] items-center justify-center rounded-full bg-slate-400/20 text-slate-600 transition-[transform,background-color,color] duration-180 ${
								showTechnicalDetails ? 'rotate-180 bg-blue-600/15 text-blue-700' : ''
							}`}
							aria-hidden="true"
						>
							<svg viewBox="0 0 20 20" fill="none" class="h-3 w-3">
								<path
									d="M6 8l4 4 4-4"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
								/>
							</svg>
						</span>
					</button>
					{#if showTechnicalDetails}
						<div
							id="error-details-panel"
							class="overflow-hidden"
							transition:slide={{ duration: 180, easing: cubicOut }}
						>
							<p
								class="mb-0 mt-3 rounded-xl border border-slate-900/10 bg-slate-50/90 px-[0.85rem] py-3 font-mono text-xs leading-normal text-slate-700 wrap-anywhere"
							>
								HTTP {status}: {rawMessage}
							</p>
						</div>
					{/if}
				</div>
			</div>
		</section>
	</div>
</div>
