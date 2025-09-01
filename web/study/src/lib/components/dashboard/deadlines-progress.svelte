<script lang="ts">
	import { courses as coursesStore } from '$lib/stores/courses';
	import type { Course } from '$lib/api/types';
	import Progress from '$lib/components/completion-progress/progress.svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Check from '@lucide/svelte/icons/check';
	import Clock from '@lucide/svelte/icons/clock';
	import Hourglass from '@lucide/svelte/icons/hourglass';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';
	import { SvelteDate } from 'svelte/reactivity';

	type DeadlineInfo =
		| { kind: 'missing'; due: Date | null; grace: Date | null; days?: number }
		| { kind: 'met' | 'risk'; due: Date; grace: Date; days?: number }
		| { kind: 'upcoming' | 'due' | 'grace'; due: Date; grace: Date; days: number };

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
	function deadlinesFor(course: Course): DeadlineInfo {
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
		if (!start) return { kind: 'missing', due: null, grace: null };

		const due = addDays(start, 15);
		const grace = addDays(start, 22);

		if (target && enrollment && enrollment > 0) {
			const pct = Math.round((completed / enrollment) * 100);
			if (pct >= target) {
				return { kind: 'met', due, grace };
			}
		}

		if (now < start) return { kind: 'upcoming', due, grace, days: daysLeft(due, now) };
		if (now <= due) return { kind: 'due', due, grace, days: daysLeft(due, now) };
		if (now <= grace) return { kind: 'grace', due, grace, days: daysLeft(grace, now) };
		return { kind: 'risk', due, grace };
	}

	function statusBadge(info: DeadlineInfo) {
		switch (info.kind) {
			case 'met':
				return {
					icon: Check,
					cls: '!gap-2 border-emerald-600 text-emerald-600',
					label: 'Target met'
				};
			case 'due':
			case 'upcoming':
				return {
					icon: Clock,
					cls: '!gap-2 border-sky-600 text-sky-600',
					label: `${info.days} ${info.days === 1 ? 'day' : 'days'} left`
				};
			case 'grace':
				return {
					icon: Hourglass,
					cls: '!gap-2 border-amber-600 text-amber-700 dark:border-amber-400 dark:text-amber-300',
					label: `Below target / Grace period: ${info.days} ${info.days === 1 ? 'day' : 'days'} left`
				};
			case 'risk':
				return {
					icon: AlertTriangle,
					cls: '!gap-2 border-red-600 text-red-600',
					label: 'Past deadline'
				};
			default:
				return null;
		}
	}

	const acceptedCourses = $derived(
		($coursesStore as Course[]).filter((c) => c.status === 'accepted')
	);

	// Only include courses within 4 weeks from their start date (already started)
	const windowedCourses = $derived.by(() => {
		const now = new SvelteDate();
		return acceptedCourses.filter((c) => {
			const start = toDate(c?.start_date);
			if (!start) return false;
			return now >= start && now <= addDays(start, 28);
		});
	});

	const coursesWithStatus = $derived.by(() =>
		windowedCourses.map((c) => ({ course: c, info: deadlinesFor(c) }))
	);

	function severity(kind: DeadlineInfo['kind']) {
		switch (kind) {
			case 'risk':
				return 0;
			case 'grace':
				return 1;
			case 'due':
				return 2;
			case 'upcoming':
				return 3;
			case 'met':
				return 4;
			default:
				return 5; // missing
		}
	}

	const sorted = $derived(
		coursesWithStatus.slice().sort((a, b) => {
			const s = severity(a.info.kind) - severity(b.info.kind);
			if (s !== 0) return s;
			const ad = a.info.days ?? 999;
			const bd = b.info.days ?? 999;
			return ad - bd;
		})
	);
	const allCourses = $derived(sorted);
</script>

<div class="rounded-md border p-4">
	<div class="mb-3">
		<h2 class="text-lg font-semibold">Pre-Assessment Progress</h2>
	</div>

	{#if acceptedCourses.length === 0}
		<div class="text-sm text-muted-foreground">No accepted courses yet.</div>
	{:else}
		<!-- Courses within first 4 weeks of start -->
		{#if allCourses.length > 0}
			<div class="mt-4">
				<div class="mb-2 text-sm text-muted-foreground">
					To be eligible for the honorarium, all of your courses in the study need to meet their
					pre-assessment completion targets.
				</div>
				<div class="flex flex-col divide-y">
					{#each allCourses as { course, info } (course.id)}
						<div class="flex flex-col gap-2 py-2 sm:flex-row sm:items-center sm:gap-4">
							<div class="min-w-0 sm:w-1/4">
								<a class="font-medium hover:underline" href={`/courses/${course.id}`}
									>{course.name ?? 'Untitled course'}</a
								>
								<div class="mt-1 text-xs text-muted-foreground">
									Target: {course.completion_rate_target ?? '—'}% • Enrolled: {course.enrollment_count ??
										'—'}
								</div>
							</div>
							{#if course.enrollment_count && course.completion_rate_target}
								<div class="flex min-w-0 items-center sm:w-1/2">
									<Progress
										value={Math.round(
											((course.preassessment_student_count || 0) / (course.enrollment_count || 1)) *
												100
										)}
										target={course.completion_rate_target}
										max={100}
										class="h-3 w-full"
										showIndicators
										textClass="text-xs"
									/>
								</div>
							{/if}
							{#if statusBadge(info)}
								<div class="flex w-full min-w-0 justify-start sm:w-1/4 sm:justify-end">
									<Badge
										variant="outline"
										class={`max-w-full min-w-0 shrink text-left leading-tight font-medium break-words whitespace-normal ${statusBadge(info)?.cls} [&>svg]:!size-4`}
									>
										{#if statusBadge(info)?.icon}
											{@const Icon = statusBadge(info)?.icon}
											<Icon />
										{/if}
										{#if info.kind === 'due' || info.kind === 'upcoming'}
											{statusBadge(info)?.label}
										{:else if info.kind === 'grace'}
											{statusBadge(info)?.label}
										{:else if info.kind === 'met'}
											{statusBadge(info)?.label}
										{:else}
											{statusBadge(info)?.label}
										{/if}
									</Badge>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<div class="mt-2 text-sm text-muted-foreground">
				No courses within the first 4 weeks of start.
			</div>
		{/if}
	{/if}
</div>
