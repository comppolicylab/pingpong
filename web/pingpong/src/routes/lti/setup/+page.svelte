<script lang="ts">
	import { Heading } from 'flowbite-svelte';
	import { goto } from '$app/navigation';
	import PingPongLogo from '$lib/components/PingPongLogo.svelte';
	import { PlusOutline, LinkOutline } from 'flowbite-svelte-icons';

	export let data;

	const { context, ltiClassId } = data;

	// Build display name: prefer course_name, then course_code, else generic
	// Previously, we used "Course Code: Course Name", but in many cases the
	// course code is included in the course name, leading to redundancy.
	const courseName = context.course_name || context.course_code || 'Your Course';

	const goToCreate = () => {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(`/lti/setup/create?lti_class_id=${ltiClassId}`);
	};

	const goToLink = () => {
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		goto(`/lti/setup/link?lti_class_id=${ltiClassId}`);
	};
</script>

<div class="v-screen flex h-[calc(100dvh-3rem)] items-center justify-center">
	<div class="flex w-11/12 max-w-3xl flex-col overflow-hidden rounded-4xl lg:w-8/12">
		<header class="bg-blue-dark-40 px-12 py-8">
			<Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
		</header>
		<div class="bg-white px-12 py-8">
			<div class="flex flex-col gap-6">
				<div class="w-full">
					<div class="mb-2 text-3xl font-medium">Welcome to PingPong!</div>
					<div class="text-lg text-gray-600">
						Set up PingPong for <span class="font-semibold">{courseName}</span>
						{#if context.course_term}
							<span class="text-gray-500">({context.course_term})</span>
						{/if}
					</div>
				</div>

				<div class="w-full">
					<p class="text-base mb-6 text-gray-700">
						Choose how you'd like to connect this course to PingPong:
					</p>

					<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
						<!-- Create New Group Card -->
						<button
							type="button"
							class="flex cursor-pointer flex-col rounded-2xl border-2 border-gray-200 p-6 text-left transition-colors hover:border-orange hover:bg-orange-light"
							onclick={goToCreate}
						>
							<div class="mb-3 flex items-center gap-3">
								<div class="flex h-10 w-10 items-center justify-center rounded-full bg-orange">
									<PlusOutline class="h-5 w-5 text-white" />
								</div>
								<span class="text-lg font-semibold">Create New Group</span>
							</div>
							<p class="text-sm text-gray-600">
								Set up a fresh PingPong group for this course. Best for new courses.
							</p>
						</button>

						<!-- Link Existing Group Card -->
						<button
							type="button"
							class="flex cursor-pointer flex-col rounded-2xl border-2 border-gray-200 p-6 text-left transition-colors hover:border-orange hover:bg-orange-light"
							onclick={goToLink}
						>
							<div class="mb-3 flex items-center gap-3">
								<div
									class="flex h-10 w-10 items-center justify-center rounded-full bg-blue-dark-40"
								>
									<LinkOutline class="h-5 w-5 text-white" />
								</div>
								<span class="text-lg font-semibold">Link Existing Group</span>
							</div>
							<p class="text-sm text-gray-600">
								Connect this course to a PingPong group you already manage.
							</p>
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</div>
