<script lang="ts">
	import * as Alert from '$lib/components/ui/alert/index.js';
	import MessageCircleQuestionMark from '@lucide/svelte/icons/message-circle-question';
</script>

<div class="flex flex-1 flex-col gap-1 px-4 py-10">
	<div class="flex flex-col gap-2">
		<h1 class="mx-auto w-full max-w-3xl scroll-m-20 text-4xl font-bold text-balance">Resources</h1>
		<p class="mx-auto w-full max-w-3xl scroll-m-20 text-base text-muted-foreground">
			Find answers to common questions and resources to help you integrate PingPong in your
			classroom.
		</p>
	</div>
	<p class="mx-auto w-full max-w-3xl scroll-m-20 pt-8 text-base">
		We have compiled the following resources for instructors:
	</p>
	<ul class="mx-auto w-full max-w-3xl scroll-m-20 list-disc pl-6 text-base [&>li]:mt-2">
		<li>
			<a
				href="https://docs.google.com/document/d/1GpY703SP7-rSFX-rEj42OfArgbQEIsNvJ2UqVDTYX-M/edit?tab=t.0#heading=h.1fob9te"
				target="_blank"
				class="text-primary underline underline-offset-4"
			>
				Support guide for using PingPong
			</a>
		</li>
		<li>
			<a
				href="https://docs.google.com/document/d/1GqP081VbD9lN7s2T7mnP3n49brd80exz-faWINdLNzQ/edit?tab=t.0"
				target="_blank"
				class="text-primary underline underline-offset-4"
			>
				List of frequently asked questions
			</a>
		</li>
		<li>
			<a
				href="https://www.youtube.com/watch?v=-JqRayLjCXc"
				target="_blank"
				class="text-primary underline underline-offset-4"
			>
				Introductory video on using PingPong for instructors
			</a>
		</li>
		<li>
			<a
				href="https://www.youtube.com/watch?v=RQawdm-LJZw"
				target="_blank"
				class="text-primary underline underline-offset-4"
			>
				Introductory video on using PingPong for students
			</a>
		</li>
		<li>
			[Optional Video]: <a
				href="https://www.youtube.com/watch?v=Lo1i09a_s90"
				target="_blank"
				class="text-primary underline underline-offset-4"
			>
				Making a custom bot in PingPong
			</a>
		</li>
	</ul>
	<Alert.Root class="mx-auto mt-6 w-full max-w-3xl text-base">
		<MessageCircleQuestionMark />
		<Alert.Title class="line-clamp-none font-normal tracking-normal"
			>If you experience any issues, please contact the PingPong study team at <a
				href="mailto:support@pingpong-hks.atlassian.net"
				class="text-nowrap text-primary underline underline-offset-4"
			>
				support@pingpong-hks.atlassian.net
			</a>.</Alert.Title
		>
	</Alert.Root>
</div>
