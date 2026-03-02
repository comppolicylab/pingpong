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

<div class="error-shell">
	<div class="card-glow-wrapper">
		<div class="gradient-orb orb-1"></div>
		<div class="gradient-orb orb-2"></div>
		<div class="gradient-orb orb-3"></div>
		<section class="error-card">
			<div class="error-content">
				<div class="error-grid">
					<div>
						<h1 class="error-title">{title}</h1>
						<p class="error-description">{description}</p>
					</div>
				</div>

				<div class="error-details">
					<button
						type="button"
						class="error-details-toggle"
						aria-expanded={showTechnicalDetails}
						aria-controls="error-details-panel"
						on:click={() => (showTechnicalDetails = !showTechnicalDetails)}
					>
						<span>Technical details</span>
						<span
							class={`summary-icon ${showTechnicalDetails ? 'is-open' : ''}`}
							aria-hidden="true"
						>
							<svg viewBox="0 0 20 20" fill="none">
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
							class="error-details-panel"
							transition:slide={{ duration: 180, easing: cubicOut }}
						>
							<p class="error-details-copy">HTTP {status}: {rawMessage}</p>
						</div>
					{/if}
				</div>
			</div>
		</section>
	</div>
</div>

<style>
	.error-shell {
		position: relative;
		display: flex;
		width: 100%;
		height: 100%;
		min-height: 100%;
		box-sizing: border-box;
		align-items: center;
		justify-content: center;
		overflow: hidden;
		padding: 1rem;
		background-color: #201e45;
	}

	.card-glow-wrapper {
		position: relative;
		width: min(100%, 52rem);
	}

	.gradient-orb {
		position: absolute;
		border-radius: 50%;
		filter: blur(120px);
		opacity: 0.5;
		pointer-events: none;
	}

	.orb-1 {
		width: 300px;
		height: 300px;
		top: -80px;
		left: -60px;
		background: radial-gradient(circle, #6d28d9 0%, transparent 70%);
	}

	.orb-2 {
		width: 280px;
		height: 280px;
		bottom: -70px;
		right: -50px;
		background: radial-gradient(circle, #2563eb 0%, transparent 70%);
	}

	.orb-3 {
		width: 240px;
		height: 240px;
		bottom: -90px;
		left: 30%;
		background: radial-gradient(circle, #db2777 0%, transparent 70%);
		opacity: 0.3;
	}

	.error-card {
		position: relative;
		z-index: 1;
		width: 100%;
		height: auto;
		border-radius: 1.75rem;
		border: 1px solid rgba(255, 255, 255, 0.3);
		background: rgba(255, 255, 255, 0.95);
		box-shadow:
			0 1px 1px rgba(15, 23, 42, 0.04),
			0 24px 50px -24px rgba(15, 23, 42, 0.24);
		backdrop-filter: saturate(160%) blur(18px);
	}

	.error-content {
		width: 100%;
		max-width: 78rem;
		margin: 0 auto;
		padding: 2.5rem 1.5rem 2.5rem;
	}

	.error-grid {
		display: grid;
		grid-template-columns: 1fr;
		gap: 2rem;
	}

	.error-title {
		margin-top: 0;
		margin-bottom: 0;
		font-size: clamp(1.35rem, 2.5vw, 2.1rem);
		line-height: 1.15;
		letter-spacing: -0.02em;
		font-weight: 600;
		color: #0f172a;
		max-width: 24ch;
	}

	.error-description {
		margin-top: 1rem;
		margin-bottom: 0;
		max-width: 62ch;
		font-size: 1rem;
		line-height: 1.7;
		color: #334155;
	}

	.error-details {
		margin-top: 1.75rem;
		padding-top: 1rem;
		border-top: 1px solid rgba(15, 23, 42, 0.08);
	}

	.error-details-toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		border: none;
		background: transparent;
		padding: 0;
		font: inherit;
		font-size: 0.85rem;
		font-weight: 600;
		color: #334155;
	}

	.summary-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.1rem;
		height: 1.1rem;
		border-radius: 9999px;
		background: rgba(148, 163, 184, 0.18);
		color: #475569;
		transition:
			transform 180ms ease,
			background-color 180ms ease,
			color 180ms ease;
	}

	.summary-icon svg {
		width: 0.75rem;
		height: 0.75rem;
	}

	.summary-icon.is-open {
		transform: rotate(180deg);
		background: rgba(37, 99, 235, 0.15);
		color: #1d4ed8;
	}

	.error-details-panel {
		overflow: hidden;
	}

	.error-details-copy {
		margin-top: 0.75rem;
		margin-bottom: 0;
		padding: 0.75rem 0.85rem;
		border-radius: 0.75rem;
		border: 1px solid rgba(15, 23, 42, 0.08);
		background: rgba(248, 250, 252, 0.9);
		font-size: 0.75rem;
		line-height: 1.5;
		font-family:
			ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New',
			monospace;
		color: #334155;
		overflow-wrap: anywhere;
	}

	@media (min-width: 768px) {
		.error-shell {
			padding: 1.5rem;
		}

		.error-content {
			padding: 3.2rem 3rem 3rem;
		}
	}
</style>
