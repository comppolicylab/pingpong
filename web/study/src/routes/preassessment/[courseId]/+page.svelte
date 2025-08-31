<script lang="ts">
	import DataTable from '$lib/components/common-table/data-table.svelte';
	import Progress from '$lib/components/completion-progress/progress.svelte';
	import { columns } from '$lib/components/preassessment-table/columns.js';
	import * as Alert from '$lib/components/ui/alert/index.js';
	import Info from '@lucide/svelte/icons/info';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import type { Course, PreAssessmentStudent } from '$lib/api/types';
	import { getPreAssessmentStudents } from '$lib/api/client';
	import { explodeResponse } from '$lib/api/utils';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { courses as coursesStore, ensureCourses } from '$lib/stores/courses';

	let preAssessmentStudents = $state([] as PreAssessmentStudent[]);
	let loading = $state(true);
	let enrollmentCount = $state<number | undefined>(undefined);
	let preAssessmentStudentCount = $state<number | undefined>(undefined);
	let completionRateTarget = $state<number | undefined>(undefined);

	onMount(async () => {
		try {
			const courseId = page.params.courseId as string;
			const [studentsRes] = await Promise.all([
				getPreAssessmentStudents(fetch, courseId).then(explodeResponse),
				ensureCourses(fetch)
			]);
			preAssessmentStudents = studentsRes.students ?? [];
			const course: Course | undefined = $coursesStore.find((c) => c.id === courseId);
			if (course) {
				enrollmentCount = course.enrollment_count;
				preAssessmentStudentCount = course.preassessment_student_count;
				completionRateTarget = course.completion_rate_target;
			}
		} catch {
			// Leave defaults; error could be surfaced in future UX
		} finally {
			loading = false;
		}
	});

	const completionRate = $derived(
		enrollmentCount && preAssessmentStudentCount
			? Math.round((preAssessmentStudentCount / enrollmentCount) * 100)
			: 0
	);
</script>

<div class="flex flex-col gap-4">
	<div class="grid grid-cols-4 gap-4">
		<div class="col-span-3 flex flex-col gap-2">
			<h2 class="text-xl font-semibold">Pre-Assessment Submissions</h2>
			{#if loading}
				<div class="space-y-2">
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
					<Skeleton class="h-8 w-full" />
				</div>
			{:else}
				<DataTable data={preAssessmentStudents} {columns} />
			{/if}
		</div>
		<div class="col-span-1 flex flex-col gap-2">
			<h2 class="text-xl font-semibold">Pre-Assessment Completion Rate</h2>
			{#if loading}
				<Skeleton class="h-4 w-full" />
				<div class="flex flex-row items-center gap-2 text-sm">
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
				<div class="flex flex-row items-center gap-2 text-sm">
					<span class="text-2xl font-bold">{preAssessmentStudentCount}/{enrollmentCount}</span>
					<span>students</span>
				</div>
			{/if}
			{#if !loading && preAssessmentStudentCount && preAssessmentStudentCount < preAssessmentStudents.length}
				<Alert.Root class="self-start">
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
			<Alert.Root class="self-start">
				<Info />
				<Alert.Title class="line-clamp-none tracking-normal"
					>Need to change your enrollment count?</Alert.Title
				>
				<Alert.Description>
					<p>
						We use your enrollment count to calculate the completion rate. Email <a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
							>support@pingpong-hks.atlassian.net</a
						> if you need to change your enrollment count.
					</p>
				</Alert.Description>
			</Alert.Root>
		</div>
	</div>
</div>
