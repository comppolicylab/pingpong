<script lang="ts">
	import * as Alert from '$lib/components/ui/alert/index.js';
	import Percent from '@lucide/svelte/icons/percent';
	import Users from '@lucide/svelte/icons/users';
	import CalendarClock from '@lucide/svelte/icons/calendar-clock';
	import { courses as coursesStore } from '$lib/stores/courses';
	import Info from '@lucide/svelte/icons/info';

	const hasAnyTreatmentCourses = $derived(
		$coursesStore.some(
			(course) => course.pingpong_group_url !== '' && course.randomization === 'treatment'
		)
	);
	const hasAnyAcceptedCourses = $derived(
		$coursesStore.some((course) => course.status === 'accepted')
	);
</script>

<div class="rounded-md border p-4">
	<h2 class="mb-3 text-lg font-semibold">Announcements</h2>

	{#if hasAnyAcceptedCourses}
		<div class="flex flex-col gap-3">
			<Alert.Root class="self-start">
				<Info />
				<Alert.Title class="line-clamp-none tracking-normal"
					>Need to change your enrollment count?</Alert.Title
				>
				<Alert.Description>
					<p>
						We use your enrollment count to calculate completion rates. Click <i>View course</i> to
						navigate to the course details page and use the <i>Change Enrollment</i> button to update
						your enrollment count.
					</p>
				</Alert.Description>
			</Alert.Root>

			<Alert.Root class="self-start">
				<Percent />
				<Alert.Title class="line-clamp-none tracking-normal">
					Available Now: Pre-assessment completion rate targets
				</Alert.Title>
				<Alert.Description>
					<p>
						You can now view completion rate targets for your accepted courses.
						<span class="font-medium">
							As a reminder, all courses in both treatment and control groups need to meet the
							completion rate targets for the pre-assessment and post-assessment to remain in the
							study and receive the honorarium.
						</span>
						Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
							>support@pingpong-hks.atlassian.net</a
						> if you have any questions.
					</p>
				</Alert.Description>
			</Alert.Root>

			<Alert.Root class="self-start">
				<Users />
				<Alert.Title class="line-clamp-none tracking-normal">
					Available Now: List of students that have completed the pre-assessment
				</Alert.Title>
				<Alert.Description>
					<p>
						You can now view real-time lists of students that have completed the pre-assessment for
						your accepted courses.
						<span class="font-medium">
							All students in your course should complete the pre-assessment, whether they are in a
							treatment or control group class, regardless of whether they agree for the research
							team to analyze their de-identified data.
						</span>
					</p>
				</Alert.Description>
			</Alert.Root>
		</div>
	{/if}

	{#if hasAnyTreatmentCourses}
		<div class="mt-3">
			<Alert.Root class="self-start">
				<CalendarClock />
				<Alert.Title class="line-clamp-none tracking-normal">
					Available Now: TutorBot assistant in your PingPong Groups
				</Alert.Title>
				<Alert.Description>
					<p>
						Courses assigned to the Treatment group have access to TutorBot, an AI-powered tutor
						developed by our team. The TutorBot assistant is now available in your PingPong Groups.
						You are welcome to create your own course-specific assistants. Email
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
							>support@pingpong-hks.atlassian.net</a
						> if you have any questions.
					</p>
				</Alert.Description>
			</Alert.Root>
		</div>
	{/if}
</div>
