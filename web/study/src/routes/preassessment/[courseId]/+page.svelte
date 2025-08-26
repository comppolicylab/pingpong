<script lang="ts">
	import DataTable from '$lib/components/common-table/data-table.svelte';
	import Progress from '$lib/components/completion-progress/progress.svelte';
	import { columns } from '$lib/components/preassessment-table/columns.js';
	import * as Alert from '$lib/components/ui/alert/index.js';
	import Info from '@lucide/svelte/icons/info';
	let { data } = $props();

	const completionRate = $derived(
		data.enrollmentCount && data.preAssessmentStudentCount
			? Math.round((data.preAssessmentStudentCount / data.enrollmentCount) * 100)
			: 0
	);
</script>

<div class="flex flex-col gap-4">
	<div class="grid grid-cols-4 gap-4">
		<div class="col-span-3 flex flex-col gap-2">
			<h2 class="text-xl font-semibold">Pre-Assessment Submissions</h2>
			<DataTable data={data.preAssessmentStudents} {columns} />
		</div>
		<div class="col-span-1 flex flex-col gap-2">
			<h2 class="text-xl font-semibold">Pre-Assessment Completion Rate</h2>
			<Progress
				value={completionRate}
				target={data.completionRateTarget}
				max={100}
				class="h-4"
				showIndicators
				textClass="text-sm"
			/>
			<div class="flex flex-row items-center gap-2 text-sm">
				<span class="text-2xl font-bold"
					>{data.preAssessmentStudentCount}/{data.enrollmentCount}</span
				>
				<span>students</span>
			</div>
			{#if data.preAssessmentStudentCount && data.enrollmentCount && data.preAssessmentStudentCount < data.enrollmentCount}
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
