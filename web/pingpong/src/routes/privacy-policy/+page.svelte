<script lang="ts">
	import { Heading, P } from 'flowbite-svelte';
	import { onMount } from 'svelte';
	import { ltiHeaderComponent, ltiHeaderProps } from '$lib/stores/ltiHeader';

	onMount(() => {
		ltiHeaderComponent.set(null);
		ltiHeaderProps.set({});
	});
</script>

<div class="about flex h-full flex-col gap-4 overflow-y-auto px-12 py-12">
	<div class="text-center">
		<Heading tag="h2" class="mt-4 mb-3" customSize="text-4xl font-extrabold md:text-5xl lg:text-6xl"
			>Privacy Policy
		</Heading>
	</div>
	<div>
		<P class="mt-4"
			>This Privacy Statement discloses the privacy practices related to the HKS developed tool,
			PingPong, in its use by Harvard affiliates at Harvard University in Cambridge, MA. By using
			PingPong, you are consenting to our collection and use of information in accordance with this
			Privacy Statement.</P
		>
	</div>
	<div>
		<Heading tag="h3" class="mt-4 mb-3" customSize="text-2xl font-extrabold"
			>What does the privacy notice in PingPong mean regarding information visible to moderators?
		</Heading>
		<ol class="ml-5 list-disc">
			<li class="my-2">
				<span class="font-semibold">Moderators can see this thread but not your name:</span> If your group
				has been configured so that moderators (typically members of the teaching team) can view de-identified
				transcripts in your group, you will see the notice: &ldquo;Moderators can see this thread but
				not your name.&rdquo; This means moderators can see conversations happening with the bot, but
				not your name or other identifiable information about you. Moderators may select this option so
				they can adjust the bot as needed, but chats will not be used to identify any individual user.
			</li>
			<li class="my-2">
				<span class="font-semibold">Moderators cannot see this thread or your name:</span> If your group
				has been configured so that neither names nor transcripts are visible to moderators (or others),
				you will see the notice: &ldquo;Moderators cannot see this thread or your name.&rdquo; This means
				moderators cannot see conversations happening or who is using this bot.
			</li>
		</ol>
	</div>
	<div>
		<Heading tag="h3" class="mt-4 mb-3" customSize="text-2xl font-extrabold"
			>What information do we gather about you and who has access?
		</Heading>
		<P class="mt-4"
			>Moderators for the group in which you are using PingPong do not have access to your
			identifiable information. The Harvard technical team developing and managing PingPong does
			have access to identifiable information for purposes of system administration, including
			system protection, maintenance, improvement, and management as well as abuse prevention, to
			track user trends to improve the quality of PingPong and the learning experience, and for the
			other purposes described in this notice and other relevant policies. The PingPong developer
			team automatically logs errors in the app to <a
				href="https://sentry.io"
				rel="noopener noreferrer"
				class="underline"
				target="_blank">Sentry</a
			>. These logs do not contain any identifiable information about any user who might have
			triggered the error. Identifiable information, per policy, cannot be requested and will not be
			provided to moderators. Generally, HKS follows the
			<a
				href="https://hwpi.harvard.edu/files/provost/files/policy_on_access_to_electronic_information.pdf"
				rel="noopener noreferrer"
				class="underline"
				target="_blank">Harvard Policy on Access to Electronic Information</a
			> in the management of PingPong and access to the user data stored to support the service.</P
		>
		<P class="mt-4"
			>Harvard researchers may request deidentified transcripts or other user data related to the
			use of PingPong for the purposes of learning about the use of PingPong and improving the
			learning experience. User information may be shared with third-party vendors to the extent
			necessary to provide PingPong services to users. For example, PingPong is built using OpenAI's
			Assistants API under the Harvard institutional license. Documents uploaded to the app are
			stored on OpenAI's servers, not our own. We are able to delete these files as necessary. For
			more information about Harvard's license with OpenAI, please contact <a
				href="mailto:sgoshev@hks.harvard.edu"
				rel="noopener noreferrer"
				class="underline"
				target="_blank">Simo Goshev</a
			>.</P
		>
		<P class="mt-4"
			>We may also provide your information to third parties in circumstances where we believe that
			doing so is necessary or appropriate to satisfy any applicable law, regulation, legal process
			or governmental request; detect, prevent or otherwise address fraud, security, or technical
			issues; or protect our rights and safety and the rights and safety of our users or others.</P
		>
	</div>

	<div>
		<Heading tag="h3" class="mt-4 mb-3" customSize="text-2xl font-extrabold"
			>Information protection
		</Heading>
		<P class="mt-4"
			>This site has reasonable security measures in place to help protect against the loss, misuse,
			and alteration of the information under our control. However, no method of transmission over
			the Internet or method of electronic storage is 100% secure.
		</P>
	</div>

	<div>
		<Heading tag="h3" class="mt-4 mb-3" customSize="text-2xl font-extrabold"
			>Changes to this policy
		</Heading>
		<P class="mt-4"
			>This Privacy Statement may be amended from time to time. Any such changes will be posted on
			this page.
		</P>
	</div>

	<div>
		<Heading tag="h3" class="mt-4 mb-3" customSize="text-2xl font-extrabold"
			>Effective date
		</Heading>
		<P class="mt-4">The effective date of this policy is August 5, 2024.</P>
	</div>
</div>
