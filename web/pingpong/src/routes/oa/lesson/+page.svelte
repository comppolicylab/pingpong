<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { afterNavigate, replaceState } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import * as api from '$lib/api';
	import ThreadDetailPage from '$lib/components/ThreadDetailPage.svelte';
	import { startOpenAccessPlayer, takeLaunchCode } from '$lib/openAccessPlayer';
	import type { OpenAccessSession } from '$lib/stores/openAccess';

	export let data;

	let lessonData: Record<string, unknown> | null = null;
	let failed = false;
	let stop: (() => void) | undefined;

	const loadLesson = async (session: OpenAccessSession, config: api.OpenAccessPlayerConfig) => {
		const threadData = await api.getThread(fetch, session.classId, session.threadId);
		const expanded = api.expandResponse(threadData);
		if (expanded.error) {
			failed = true;
			return;
		}
		lessonData = {
			...data,
			threadData,
			threadModel: expanded.data.model || '',
			threadInteractionMode: expanded.data.thread.interaction_mode || 'chat',
			availableTools: expanded.data.tools_available || '',
			canDeleteThread: false,
			threadDeletionDisabledByModerators: false,
			canPublishThread: false,
			canViewAssistant: true,
			threadRecording: null,
			threadDisplayUserInfo: false,
			threadLectureVideoMismatch: false,
			threadLectureSlideMismatch: expanded.data.lecture_slide_matches_assistant === false,
			class: undefined,
			assistants: [],
			uploadInfo: api.uploadInfoFrom(),
			isSupervisor: false,
			supervisors: [],
			maxMessageLength: config.message_max_characters
		};
	};

	afterNavigate(() => {
		if (window.location.hash) replaceState(resolve('/oa/lesson'), $page.state);
	});

	onMount(async () => {
		const launchCode = takeLaunchCode(window.location.hash);
		stop = await startOpenAccessPlayer(fetch, launchCode, {
			onSession: loadLesson,
			onError: () => {
				failed = true;
			}
		});
	});

	onDestroy(() => stop?.());
</script>

<div class="oa-player h-dvh w-full p-4">
	<div class="h-full overflow-y-auto rounded-4xl bg-white">
		{#if lessonData && !failed}
			<ThreadDetailPage data={lessonData} />
		{:else if failed}
			<div class="flex h-full items-center justify-center p-6 text-center text-gray-600">
				This lesson is not available right now.
			</div>
		{/if}
	</div>
</div>
