<script lang="ts">
	import * as Accordion from '$lib/components/ui/accordion/index.js';
	import { courses as coursesStore } from '$lib/stores/courses';
	const hasAnyTreatmentCourses = $derived(
		$coursesStore.some(
			(course) => course.pingpong_group_url !== '' && course.randomization === 'treatment'
		)
	);
	const hasAnyControlCourses = $derived(
		$coursesStore.some(
			(course) => course.pingpong_group_url === '' && course.randomization === 'control'
		)
	);
</script>

<div class="rounded-md border p-4">
	<h2 class="mb-3 text-lg font-semibold">FAQ</h2>

	<Accordion.Root type="single" class="w-full" value="pingpongAccess">
		{#if hasAnyTreatmentCourses}
			<Accordion.Item value="pingpongAccess">
				<Accordion.Trigger>How do my students get access to PingPong?</Accordion.Trigger>
				<Accordion.Content>
					<div class="pb-4 text-sm leading-relaxed text-muted-foreground">
						Students in a treatment course will receive access to PingPong shortly after they
						complete the pre-assessment. An email invite will be sent from noreply@hks.harvard.edu
						to the academic and personal email addresses they provide during the pre-assessment. If
						students do not see the email, please ask them to check their spam/junk folder.
					</div>
					<div class="pb-4 text-sm leading-relaxed text-muted-foreground">
						<strong>Please do not manually add students to PingPong.</strong> If your students face
						any login issues, please contact
						<a
							href="mailto:support@pingpong-hks.atlassian.net"
							class="text-nowrap text-primary underline underline-offset-4 hover:text-primary/80"
							>support@pingpong-hks.atlassian.net</a
						>.
					</div>
				</Accordion.Content>
			</Accordion.Item>
		{/if}

		{#if hasAnyControlCourses}
			<Accordion.Item value="controlPreAssessment">
				<Accordion.Trigger>
					Do students in control courses need to complete the pre- and post-assessments?
				</Accordion.Trigger>
				<Accordion.Content>
					<div class="pb-4 text-sm leading-relaxed text-muted-foreground">
						Yes, all students in control courses should complete the pre- and post-assessments.
						Results from these assessments will help us understand PingPong's impact on students'
						learning.
					</div>
					<div class="pb-4 text-sm leading-relaxed text-muted-foreground">
						Please remember: as an instructor in control courses, your class is in the study but
						will not have access to PingPong until the semester after the study has concluded. As
						always, our team is here to support you—please don’t hesitate to reach out with
						questions.
					</div>
				</Accordion.Content>
			</Accordion.Item>
		{/if}

		<Accordion.Item value="contact">
			<Accordion.Trigger>Who can I contact with questions?</Accordion.Trigger>
			<Accordion.Content>
				<div class="pb-4 text-sm leading-relaxed text-muted-foreground">
					Email
					<a
						href="mailto:support@pingpong-hks.atlassian.net"
						class="text-primary underline underline-offset-4 hover:text-primary/80"
						>support@pingpong-hks.atlassian.net</a
					> for assistance.
				</div>
			</Accordion.Content>
		</Accordion.Item>
	</Accordion.Root>
</div>
