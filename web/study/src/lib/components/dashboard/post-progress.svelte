<script lang="ts">
	import { resolve } from '$app/paths';
	import { courses as coursesStore } from '$lib/stores/courses';
	import type { Course } from '$lib/api/types';
	import Progress from '$lib/components/completion-progress/progress.svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import Check from '@lucide/svelte/icons/check';
	import Clock from '@lucide/svelte/icons/clock';
	import AlertTriangle from '@lucide/svelte/icons/alert-triangle';

	const acceptedCourses = $derived(
		($coursesStore as Course[]).filter((c) => c.status === 'accepted')
	);

	type ProgressEntry = {
		course: Course;
		enrollment: number | null;
		completed: number;
		target: number | null;
		pct: number | null;
	};

	const coursesWithProgress = $derived.by<ProgressEntry[]>(() =>
		acceptedCourses.map((course) => {
			const enrollment =
				typeof course?.enrollment_count === 'number' ? course.enrollment_count : null;
			const completed =
				typeof course?.postassessment_student_count === 'number'
					? course.postassessment_student_count
					: 0;
			const target =
				typeof course?.completion_rate_target === 'number' ? course.completion_rate_target : null;
			const pct =
				enrollment && enrollment > 0
					? Math.round((completed / enrollment) * 100)
					: completed > 0
						? 0
						: null;
			return { course, enrollment, completed, target, pct };
		})
	);

	function severity({ pct, target }: ProgressEntry) {
		if (target === null || pct === null) return 1; // missing data
		if (pct >= target) return 2; // lowest urgency
		return 0; // below target
	}

	function statusBadge(entry: ProgressEntry) {
		const { pct, target } = entry;
		if (target === null || pct === null) {
			return {
				icon: AlertTriangle,
				cls: '!gap-2 border-muted-foreground/50 text-muted-foreground',
				label: 'Needs data'
			};
		}
		if (pct >= target) {
			return {
				icon: Check,
				cls: '!gap-2 border-emerald-600 text-emerald-600',
				label: 'Target met'
			};
		}
		return {
			icon: Clock,
			cls: '!gap-2 border-sky-600 text-sky-600',
			label: `${pct}% complete`
		};
	}

	const sorted = $derived(
		coursesWithProgress.slice().sort((a, b) => {
			const s = severity(a) - severity(b);
			if (s !== 0) return s;
			const aPct = a.pct ?? -1;
			const bPct = b.pct ?? -1;
			return aPct - bPct;
		})
	);
</script>

<div class="rounded-md border p-4">
	<div class="mb-3">
		<h2 class="text-lg font-semibold">Post-Assessment Progress</h2>
	</div>

	{#if acceptedCourses.length === 0}
		<div class="text-sm text-muted-foreground">No accepted courses yet.</div>
	{:else if sorted.length === 0}
		<div class="text-sm text-muted-foreground">
			No post-assessment data yet. Post-assessment progress will appear here once submissions start.
		</div>
	{:else}
		<div class="flex flex-col divide-y">
			{#each sorted as entry (entry.course.id)}
				<div class="flex flex-col gap-2 py-2 sm:flex-row sm:items-center sm:gap-4">
					<div class="min-w-0 sm:w-1/4">
						<a class="font-medium hover:underline" href={resolve(`/courses/${entry.course.id}`)}
							>{entry.course.name ?? 'Untitled course'}</a
						>
						<div class="mt-1 text-xs text-muted-foreground">
							Target: {entry.target ?? '—'}% • Enrolled: {entry.enrollment ?? '—'}
						</div>
					</div>
					<div class="flex min-w-0 items-center sm:w-1/2">
						<Progress
							value={entry.pct ?? 0}
							target={entry.target ?? undefined}
							max={100}
							class="h-3 w-full"
							showIndicators
							textClass="text-xs"
						/>
					</div>
					{#if statusBadge(entry)}
						{@const badge = statusBadge(entry)}
						<div class="flex w-full min-w-0 justify-start sm:w-1/4 sm:justify-end">
							<Badge
								variant="outline"
								class={`max-w-full min-w-0 shrink text-left leading-tight font-medium break-words whitespace-normal ${badge.cls} [&>svg]:!size-4`}
							>
								{#if badge.icon}
									{@const Icon = badge.icon}
									<Icon />
								{/if}
								{badge.label}
							</Badge>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
