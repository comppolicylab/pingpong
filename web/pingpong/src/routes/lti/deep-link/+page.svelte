<script lang="ts">
	import LTIDeepLinkPicker from '$lib/components/LTIDeepLinkPicker.svelte';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import * as api from '$lib/api';
	import { DEEP_LINK_SUBTITLE, DEEP_LINK_TITLE } from '$lib/ltiDeepLink';
	import { loading } from '$lib/stores/general';

	export let data;

	const { context, deepLinkSessionId } = data;
	let errorMessage = '';

	const postToCanvas = (response: api.LTIDeepLinkCompleteResponse) => {
		const form = document.createElement('form');
		form.method = 'POST';
		form.action = response.deep_link_return_url;
		const jwt = document.createElement('input');
		jwt.type = 'hidden';
		jwt.name = 'JWT';
		jwt.value = response.jwt;
		form.appendChild(jwt);
		document.body.appendChild(form);
		form.submit();
	};

	const complete = async (
		destination: api.LTIDeepLinkDestination,
		assistantId: number | null = null,
		simpleView = false
	) => {
		errorMessage = '';
		$loading = true;
		try {
			const result = await api
				.completeLTIDeepLink(
					fetch,
					deepLinkSessionId,
					destination,
					destination === 'assistant' ? assistantId : null,
					destination === 'assistant' && simpleView
				)
				.then(api.expandResponse);
			if (result.error || !result.data) {
				errorMessage = result.error?.detail || 'Unable to return this selection to Canvas.';
				return;
			}
			postToCanvas(result.data);
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'Unable to complete this selection.';
		} finally {
			$loading = false;
		}
	};
</script>

<div class="lti-deep-link flex h-dvh items-center justify-center p-4 md:p-8 lti-compact:py-0">
	<div class="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-4xl bg-white">
		<header
			class="flex shrink-0 items-center justify-center gap-4 bg-blue-dark-40 px-6 py-6 md:px-10 lti-compact:justify-between lti-compact:py-3"
		>
			<h1 class="logo shrink-0 lti-compact:[&_svg]:h-8 lti-compact:[&_svg]:w-auto">
				<PingPongLogo size="full" />
			</h1>
			<div class="hidden min-w-0 flex-1 text-right lti-compact:block">
				<p class="truncate text-sm font-semibold text-white">{DEEP_LINK_TITLE}</p>
				<p class="truncate text-xs text-blue-light-40">{DEEP_LINK_SUBTITLE}</p>
			</div>
		</header>

		<LTIDeepLinkPicker
			{context}
			{errorMessage}
			busy={$loading}
			onSubmit={complete}
			onCancel={() => complete('cancel')}
		/>
	</div>
</div>
