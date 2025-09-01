<script lang="ts">
	import * as Alert from '$lib/components/ui/alert/index.js';
	import Info from '@lucide/svelte/icons/info';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import DataTable from '$lib/components/common-table/data-table.svelte';
	import Progress from '$lib/components/completion-progress/progress.svelte';
	import { columns } from '$lib/components/preassessment-table/columns.js';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import type { Course, PreAssessmentStudent } from '$lib/api/types';
	import { getPreAssessmentStudents } from '$lib/api/client';
	import { explodeResponse } from '$lib/api/utils';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { courses as coursesStore, ensureCourses } from '$lib/stores/courses';
	import StatusBadge from '$lib/components/classes-table/status-badge.svelte';
	import RandomizationBadge from '$lib/components/classes-table/randomization-badge.svelte';
	import UrlCopyable from '$lib/components/classes-table/data-table-url-copyable.svelte';
	import Button from '$lib/components/ui/button/button.svelte';
	import CourseTimeline from '$lib/components/course-timeline.svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Check from '@lucide/svelte/icons/check';
	import Clock from '@lucide/svelte/icons/clock';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import { SvelteDate } from 'svelte/reactivity';

	let preAssessmentStudents = $state([] as PreAssessmentStudent[]);
	let loading = $state(true);

	const course = $derived(
		($coursesStore as Course[]).find((c) => c.id === (page.params.courseId as string))
	);

	onMount(async () => {
		try {
			const courseId = page.params.courseId as string;
			const [studentsRes] = await Promise.all([
				getPreAssessmentStudents(fetch, courseId).then(explodeResponse),
				ensureCourses(fetch)
			]);
			preAssessmentStudents = studentsRes.students ?? [];
		} catch {
			// Leave defaults; error could be surfaced in future UX
		} finally {
			loading = false;
		}
	});

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
	function daysLeft(to: Date, from: Date) {
		const ms = to.getTime() - from.getTime();
		return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
	}
	function daysLabel(n?: number) {
		if (typeof n !== 'number') return '';
		return `${n} ${n === 1 ? 'day' : 'days'}`;
	}
	const enrollmentCount = $derived(course?.enrollment_count);
	const preAssessmentStudentCount = $derived(course?.preassessment_student_count);
	const completionRateTarget = $derived(course?.completion_rate_target);
	const completionRate = $derived(
		enrollmentCount && preAssessmentStudentCount
			? Math.round((preAssessmentStudentCount / enrollmentCount) * 100)
			: 0
	);

	const deadlines = $derived.by(() => {
		const now = new SvelteDate();
		const start = toDate(course?.start_date);
		const target =
			typeof course?.completion_rate_target === 'number'
				? course?.completion_rate_target
				: undefined;
		const enrollment =
			typeof course?.enrollment_count === 'number' ? course?.enrollment_count : undefined;
		const completed =
			typeof course?.preassessment_student_count === 'number'
				? course?.preassessment_student_count
				: 0;

		if (!start || !target || !enrollment || enrollment <= 0) {
			return { kind: 'missing' as const, due: null as Date | null, grace: null as Date | null };
		}

		const pct = Math.round((completed / enrollment) * 100);
		if (pct >= target) {
			return { kind: 'met' as const, due: addDays(start, 14), grace: addDays(start, 21) };
		}

		const due = addDays(start, 14);
		const grace = addDays(start, 21);

		if (now < start) {
			return { kind: 'upcoming' as const, due, grace, days: daysLeft(due, now) };
		} else if (now <= due) {
			return { kind: 'due' as const, due, grace, days: daysLeft(due, now) };
		} else if (now <= grace) {
			return { kind: 'grace' as const, due, grace, days: daysLeft(grace, now) };
		}
		return { kind: 'risk' as const, due, grace };
	});
</script>

<div class="grid grid-cols-3 gap-4">
	<div class="col-span-2 flex flex-col gap-4">
		{#if deadlines.kind === 'grace'}
			<Alert.Root
				class="self-start border-amber-600 bg-transparent text-amber-700 dark:border-amber-400 dark:text-amber-300"
			>
				<Hourglass />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal"
					>Pre-Assessment Grace Period / {daysLabel(deadlines.days)} left</Alert.Title
				>
				<Alert.Description class="text-amber-700 dark:text-amber-300">
					<span>
						Your course has not reached the pre-assessment completion target. We're allowing you an
						extra week to reach the completion target to remain in the study.
					</span>
					<span>
						Extenuating circumstances? Email us at <a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-amber-700 underline underline-offset-4 hover:text-amber-600 dark:text-amber-300 dark:hover:text-amber-500"
							>support@pingpong-hks.atlassian.net</a
						>.
					</span>
				</Alert.Description>
			</Alert.Root>
		{/if}
		{#if deadlines.kind === 'risk'}
			<Alert.Root
				class="self-start border-red-600 bg-transparent text-red-700 dark:border-red-400 dark:text-red-300"
			>
				<AlertTriangle />
				<Alert.Title class="line-clamp-none font-semibold tracking-normal"
					>Pre-Assessment Target Missed</Alert.Title
				>
				<Alert.Description class="text-red-700 dark:text-red-300">
					<span>
						Your course did not meet the pre-assessment completion target. Our team will follow up
						with you to discuss next steps.
					</span>
					<span>
						Extenuating circumstances? Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-red-700 underline underline-offset-4 hover:text-red-600 dark:text-red-300 dark:hover:text-red-400"
							>support@pingpong-hks.atlassian.net</a
						>.
					</span>
				</Alert.Description>
			</Alert.Root>
		{/if}
		<!-- Overview & Completion -->
		<div class="rounded-md border p-4">
			<h2 class="mb-3 text-lg font-semibold">Course Overview</h2>
			{#if !course}
				<div class="space-y-2">
					<Skeleton class="h-5 w-1/3" />
					<Skeleton class="h-5 w-1/4" />
					<Skeleton class="h-5 w-1/2" />
					<Skeleton class="h-5 w-1/3" />
				</div>
			{:else}
				<div class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
					<div class="text-muted-foreground">Status</div>
					<div><StatusBadge status={course.status || 'in_review'} /></div>

					<div class="text-muted-foreground">Randomization</div>
					<div>
						{#if course.randomization}<RandomizationBadge
								status={course.randomization}
							/>{:else}<span class="text-muted-foreground">Not assigned</span>{/if}
					</div>

					<div class="text-muted-foreground">Start date</div>
					<div>
						{course.start_date
							? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(
									new SvelteDate(String(course.start_date))
								)
							: '—'}
					</div>

					<div class="text-muted-foreground">Enrollment</div>
					<div>{course.enrollment_count ?? '—'}</div>

					<div class="text-muted-foreground">PingPong Group</div>
					<div class="flex items-center gap-2">
						{#if course.pingpong_group_url}
							<Button
								variant="outline"
								size="sm"
								href={course.pingpong_group_url}
								target="_blank"
								rel="noopener noreferrer"
							>
								<ExternalLink size={14} /> Open
							</Button>
							<UrlCopyable url={course.pingpong_group_url} />
						{:else}
							<span class="text-muted-foreground">Not assigned</span>
						{/if}
					</div>

					<div class="text-muted-foreground">Pre-assessment Form</div>
					<div class="flex items-center gap-2">
						{#if course.preassessment_url}
							<Button
								variant="outline"
								size="sm"
								href={course.preassessment_url}
								target="_blank"
								rel="noopener noreferrer"
							>
								<ExternalLink size={14} /> Open
							</Button>
							<UrlCopyable url={course.preassessment_url} />
						{:else}
							<span class="text-muted-foreground">Not assigned</span>
						{/if}
					</div>
				</div>
			{/if}
		</div>

		<div class="rounded-md border p-4">
			<div class="mb-3 flex items-center justify-between">
				<h2 class="text-lg font-semibold">Pre-Assessment Completion</h2>
				{#if !loading && course}
					{#if deadlines.kind === 'met'}
						<Badge
							variant="outline"
							class="!gap-2 border-emerald-600 bg-transparent text-sm text-emerald-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
						>
							<Check />
							Target met
						</Badge>
					{:else if deadlines.kind === 'due' || deadlines.kind === 'upcoming'}
						<Badge
							variant="outline"
							class="!gap-2 border-sky-600 bg-transparent text-sm text-sky-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
						>
							<Clock />
							Below target / {daysLabel(deadlines.days)} left
						</Badge>
					{:else if deadlines.kind === 'grace'}
						<Badge
							variant="outline"
							class="!gap-2 border-amber-600 bg-transparent text-sm text-amber-700 dark:border-amber-400 dark:text-amber-300 [&>svg]:!size-4 [a&]:hover:bg-transparent"
						>
							<Hourglass />
							Below target / Grace period: {daysLabel(deadlines.days)} left
						</Badge>
					{:else if deadlines.kind === 'risk'}
						<Badge
							variant="outline"
							class="!gap-2 border-red-600 bg-transparent text-sm text-red-600 [&>svg]:!size-4 [a&]:hover:bg-transparent"
						>
							<AlertTriangle />
							Below target / Past deadline
						</Badge>
					{/if}
				{/if}
			</div>
			{#if loading || !course}
				<Skeleton class="h-4 w-full" />
				<div class="mt-2 flex flex-row items-center gap-2 text-sm">
					<Skeleton class="h-6 w-24" />
					<span>students</span>
				</div>
			{:else}
				<Progress
					value={completionRate}
					target={completionRateTarget}
					max={100}
					class="h-4"
					showIndicators
					textClass="text-sm"
				/>
				<div class="mt-2 flex flex-row items-center gap-2 text-sm">
					<span class="text-2xl font-bold">{preAssessmentStudentCount}/{enrollmentCount}</span>
					<span>students</span>
				</div>
				{#if preAssessmentStudentCount && preAssessmentStudentCount < preAssessmentStudents.length}
					<Alert.Root class="mt-3 self-start">
						<Info />
						<Alert.Title class="line-clamp-none tracking-normal"
							>Student count lower than submission count</Alert.Title
						>
						<Alert.Description>
							<p>
								Some students have submitted the pre-assessment multiple times. We group submissions
								by email address. Email <a
									href="mailto:support@pingpong-hks.atlassian.net"
									class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
									>support@pingpong-hks.atlassian.net</a
								> if you have any questions.
							</p>
						</Alert.Description>
					</Alert.Root>
				{/if}
			{/if}
			<Alert.Root class="mt-3 self-start">
				<Info />
				<Alert.Title class="line-clamp-none tracking-normal"
					>Need to change your enrollment count?</Alert.Title
				>
				<Alert.Description>
					<p>
						We use your enrollment count to calculate the completion rate. Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
							>support@pingpong-hks.atlassian.net</a
						>
						if you need to change your enrollment count.
					</p>
				</Alert.Description>
			</Alert.Root>
		</div>

		<!-- Submissions -->
		<div class="flex flex-col gap-2">
			<h2 class="text-lg font-semibold">Pre-Assessment Submissions</h2>
			{#if loading}
				<div class="space-y-2">
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
				</div>
			{:else}
				<DataTable data={preAssessmentStudents} {columns}>
					{#snippet empty()}
						No pre-assessment submissions yet.
					{/snippet}
				</DataTable>
			{/if}
		</div>
	</div>
	<div class="col-span-1">
		<CourseTimeline course={course as Course} />
	</div>
</div>
