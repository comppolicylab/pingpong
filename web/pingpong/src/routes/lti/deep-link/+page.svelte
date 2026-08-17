<script lang="ts">
	import { Heading } from 'flowbite-svelte';
	import LTIDeepLinkPicker from '$lib/components/LTIDeepLinkPicker.svelte';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import * as api from '$lib/api';
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

<div class="v-screen flex min-h-[calc(100dvh-3rem)] items-center justify-center py-8">
	<div
		class="flex max-h-[calc(100dvh-5rem)] w-11/12 max-w-3xl flex-col overflow-hidden rounded-4xl bg-white lg:w-9/12"
	>
		<header class="shrink-0 bg-blue-dark-40 px-8 py-6">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
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
