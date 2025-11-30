<script lang="ts">
	import DataTable from '$lib/components/common-table/data-table.svelte';
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
	import DeadlinesProgress from '$lib/components/dashboard/deadlines-progress.svelte';
	import PostProgress from '$lib/components/dashboard/post-progress.svelte';
	import Announcements from '$lib/components/dashboard/announcements.svelte';
	import FAQ from '$lib/components/dashboard/faq.svelte';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import { SvelteDate } from 'svelte/reactivity';

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

	// Grace-period session notice (per tab)
	const GRACE_NOTICE_SESSION_KEY = 'notice.grace.v1.session_shown';
	let showGraceNoticeDialog = $state(false);

	function toDate(v?: string) {
		if (!v) return null;
		const d = new SvelteDate(v);
		return isNaN(d.getTime()) ? null : d;
	}
	function addDays(base: Date, days: number) {
		const d = new SvelteDate(base);
		d.setDate(d.getDate() + days);
		return d;
	}
	const graceCourses = $derived.by(() => {
		const now = new SvelteDate();
		return ($coursesStore as Course[]).filter((c) => {
			const start = toDate(c?.start_date);
			if (!start) return false;
			const due = addDays(start, 15);
			const grace = addDays(start, 22);
			const enrollment = typeof c?.enrollment_count === 'number' ? c.enrollment_count : undefined;
			const completed =
				typeof c?.preassessment_student_count === 'number' ? c.preassessment_student_count : 0;
			const target =
				typeof c?.completion_rate_target === 'number' ? c.completion_rate_target : undefined;
			if (target && enrollment && enrollment > 0) {
				const pct = Math.round((completed / enrollment) * 100);
				if (pct >= target) return false; // already met
			}
			return start && now > due && now <= grace;
		});
	});

	$effect(() => {
		if (!browser) return;
		if ($coursesLoading) return;
		const alreadyShown = sessionStorage.getItem(GRACE_NOTICE_SESSION_KEY) === '1';
		if (!alreadyShown && graceCourses.length > 0) {
			showGraceNoticeDialog = true;
			sessionStorage.setItem(GRACE_NOTICE_SESSION_KEY, '1');
		}
	});
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

	<!-- Grace Period Notice: shown once per tab session when any course is in grace -->
	<Dialog.Root bind:open={showGraceNoticeDialog}>
		<Dialog.Content>
			<div class="relative -mx-6 -mt-6 mb-4 h-36 overflow-hidden rounded-t-lg">
				<img
					src={asset('/notice.grace.v1.webp')}
					alt=""
					class="absolute inset-0 h-full w-full object-cover"
				/>
				<div class="absolute inset-0 flex items-center justify-center">
					<Hourglass class="size-10 text-white drop-shadow" />
				</div>
			</div>
			<Dialog.Header>
				<Dialog.Title>Course(s) below completion target</Dialog.Title>
				<Dialog.Description>
					One or more of your accepted courses are currently below their completion target. We're
					allowing you an extra week to reach the completion target and remain in the study.
				</Dialog.Description>
			</Dialog.Header>
			<Dialog.Footer>
				{#if graceCourses.length > 0}
					<Button href={`/courses/${graceCourses[0].id}`}>Review course</Button>
				{/if}
				<Button variant="ghost" onclick={() => (showGraceNoticeDialog = false)}>Got it</Button>
			</Dialog.Footer>
		</Dialog.Content>
	</Dialog.Root>

	<div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
		<div class="flex flex-col gap-4 lg:col-span-2">
			{#if $coursesLoading}
				<Skeleton class="h-40 w-full" />
			{:else}
				<DeadlinesProgress />
			{/if}
			{#if $coursesLoading}
				<Skeleton class="h-40 w-full" />
			{:else}
				<PostProgress />
			{/if}

			<div>
				<h2 class="mb-2 text-xl font-semibold">Your Courses</h2>
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
		</div>
		<div class="lg:col-span-1">
			{#if $coursesLoading}
				<Skeleton class="h-80 w-full" />
			{:else}
				<Announcements />
				<div class="mt-4">
					<FAQ />
				</div>
			{/if}
		</div>
	</div>
</div>
