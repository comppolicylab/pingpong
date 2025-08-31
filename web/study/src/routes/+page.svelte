<script lang="ts">
	import * as Alert from '$lib/components/ui/alert/index.js';
	import Info from '@lucide/svelte/icons/info';
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import DataTable from '$lib/components/common-table/data-table.svelte';
	import Percent from '@lucide/svelte/icons/percent';
	import Users from '@lucide/svelte/icons/users';
	import User from '@lucide/svelte/icons/user';
	import * as Dialog from '$lib/components/ui/dialog/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { browser } from '$app/environment';
	import { asset } from '$app/paths';
	import { page } from '$app/state';
	import { markNoticeSeen } from '$lib/api/client';
	import { columns } from '$lib/components/classes-table/columns.js';
	import { onMount } from 'svelte';
	import type { Course } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import {
		courses as coursesStore,
		loading as coursesLoading,
		ensureCourses
	} from '$lib/stores/courses';

	onMount(async () => {
		try {
			await ensureCourses(fetch);
		} catch {
			// ignore; skeleton/empty will show
		}
	});

	const PROFILE_MOVED_NOTICE_KEY = 'notice.profile_moved.v1';
	let showProfileMovedDialog = $state(false);
	let hasShownProfileMovedDialog = $state(false);
	let noticeSeenMarked = $state(false);
	onMount(() => {
		if (!browser) return;
		try {
			const alreadySeen = Boolean(page.data?.feature_flags?.flags?.[PROFILE_MOVED_NOTICE_KEY]);
			if (!alreadySeen) {
				showProfileMovedDialog = true;
				hasShownProfileMovedDialog = true;
			}
		} catch {
			// ignore storage failures
		}
	});

	async function onDismissNotice() {
		showProfileMovedDialog = false;
	}

	$effect(() => {
		if (hasShownProfileMovedDialog && !showProfileMovedDialog && !noticeSeenMarked) {
			noticeSeenMarked = true;
			markNoticeSeen(fetch, PROFILE_MOVED_NOTICE_KEY).catch(() => {});
		}
	});

	const hasAnyTreatmentCourses = $derived(
		$coursesStore.some(
			(course) => course.pingpong_group_url !== '' && course.randomization === 'treatment'
		)
	);
	const hasAnyAcceptedCourses = $derived(
		$coursesStore.some((course) => course.status === 'accepted')
	);
</script>

<div class="flex flex-col gap-4">
	<Dialog.Root bind:open={showProfileMovedDialog}>
		<Dialog.Content>
			<div class="relative -mx-6 -mt-6 mb-4 h-36 overflow-hidden rounded-t-lg">
				<img
					src={asset('/notice.profile_moved.v1.webp')}
					alt=""
					class="absolute inset-0 h-full w-full object-cover"
				/>
				<div class="absolute inset-0 flex items-center justify-center">
					<User class="size-10 text-white drop-shadow" />
				</div>
			</div>
			<Dialog.Header>
				<Dialog.Title>A new page for your personal details</Dialog.Title>
				<Dialog.Description>
					We've moved your instructor details to a separate Profile page, accessible from the
					sidebar.
				</Dialog.Description>
			</Dialog.Header>
			<Dialog.Footer>
				<Button
					onclick={async () => {
						await onDismissNotice();
						window.location.href = '/profile';
					}}>Go to Profile</Button
				>
				<Button variant="ghost" onclick={onDismissNotice}>Got it</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>
	<Alert.Root>
		<Info />
		<Alert.Title class="line-clamp-none tracking-normal"
			>Welcome to your new PingPong College Study Dashboard!</Alert.Title
		>
		<Alert.Description>
			<p>
				You'll soon be able to edit your course details below. In the meantime, please email <a
					href="mailto:support@pingpong-hks.atlassian.net"
					class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
					>support@pingpong-hks.atlassian.net
				</a> if any of the information listed on this dashboard is incorrect.
			</p>
		</Alert.Description>
	</Alert.Root>

	<h2 class="mt-4 text-xl font-semibold">Your Courses</h2>
	{#if hasAnyAcceptedCourses}
		<div class="grid grid-cols-2 gap-4">
			<Alert.Root class="self-start">
				<Percent />
				<Alert.Title class="line-clamp-none tracking-normal"
					>Available Now: Pre-assessment completion rate targets</Alert.Title
				>
				<Alert.Description>
					<p>
						You can now view completion rate targets for your accepted courses. <span
							class="font-medium"
							>As a reminder, all courses in both treatment and control groups need to meet the
							completion rate targets for the pre-assessment and post-assessment to remain in the
							study and receive the honorarium.</span
						>
						Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
							>support@pingpong-hks.atlassian.net
						</a> if you have any questions.
					</p>
				</Alert.Description>
			</Alert.Root>
			<Alert.Root class="self-start">
				<Users />
				<Alert.Title class="line-clamp-none tracking-normal"
					>Available Now: List of students that have completed the pre-assessment</Alert.Title
				>
				<Alert.Description>
					<p>
						You can now view real-time lists of students that have completed the pre-assessment for
						your accepted courses. <span class="font-medium"
							>All students in your course should complete the pre-assessment, whether they are in a
							treatment or control group class, regardless of whether they agree for the research
							team to analyze their de-identified data.</span
						>
					</p>
				</Alert.Description>
			</Alert.Root>
		</div>
	{/if}

	{#if hasAnyTreatmentCourses}
		<Alert.Root class="self-start">
			<CalendarClock />
			<Alert.Title class="line-clamp-none tracking-normal"
				>Available Now: TutorBot assistant in your PingPong Groups</Alert.Title
			>
			<Alert.Description>
				<p>
					Courses assigned to the Treatment group have access to TutorBot, an AI-powered tutor
					developed by our team. The TutorBot assistant is now available in your PingPong Groups.
					You are welcome to create your own course-specific assistants. Email <a
						href="mailto:support@pingpong-hks.atlassian.net"
						class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
						>support@pingpong-hks.atlassian.net
					</a> if you have any questions.
				</p>
			</Alert.Description>
		</Alert.Root>
	{/if}

	{#if $coursesLoading}
		<div class="mt-2 space-y-2">
			<Skeleton class="h-8 w-full" />
			<Skeleton class="h-8 w-full" />
			<Skeleton class="h-8 w-full" />
			<Skeleton class="h-8 w-full" />
		</div>
	{:else}
		<DataTable data={$coursesStore as Course[]} {columns}>
			{#snippet empty()}
				We couldn't find any courses for you.<br />
				Please contact the study administrator if you think this is an error.
			{/snippet}
		</DataTable>
	{/if}
</div>
