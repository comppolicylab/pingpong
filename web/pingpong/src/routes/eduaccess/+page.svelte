<script lang="ts">
	import { Button, Card, Heading, P } from 'flowbite-svelte';
	import { ArrowRightOutline } from 'flowbite-svelte-icons';
	import PingPongEduAccessCarousel from '$lib/components/PingPongEduAccessCarousel.svelte';
</script>

<div class="about flex h-full flex-col gap-4 overflow-y-auto px-4 py-8 md:px-12 md:py-12">
	<div class="flex min-w-full flex-col text-center">
		<Heading tag="h2" class="mt-4 mb-2" customSize="text-4xl font-extrabold md:text-5xl lg:text-6xl"
			><span
				class="bg-gradient-to-t from-blue-dark-50 to-blue-dark-30 bg-clip-text text-transparent"
				>Educational Access</span
			>
		</Heading>
		<P
			class="mt-4 text-center text-xl text-gray-700 sm:px-16 md:px-25 md:px-35 lg:text-2xl xl:px-48"
			>Participate in a study evaluating the impact of AI on student learning at two- and four-year
			colleges.
		</P>
	</div>
	<div class="mx-7 mb-2">
		<P class="mt-4 leading-6"
			><b>PingPong</b> is an AI-powered virtual teaching assistant based on ChatGPT, developed by students
			and teachers at Harvard. PingPong is designed to help students with homework without giving them
			the answers, much like a human tutor. Our study aims to assess how PingPong and similar AI tools
			can improve education.</P
		>
		<P class="mt-4"
			>We are seeking instructors at <b>two- and four-year colleges</b>, especially those teaching
			math, economics, statistics and/or computer science, to participate in a randomized
			large-scale study. Initial access to PingPong will be provided to half of the participating
			instructors, with access provided to all instructors in the following semester. An
			<b>honorarium of $1,000</b> will be available to all eligible participating instructors, along with
			the opportunity to earn bonuses for referring other eligible instructors.</P
		>
		<P class="mt-4"
			>We are now considering applications for Spring 2026 courses. <b
				>To participate, complete the application linked below to confirm your eligibility.
			</b>Our team will be in touch on a rolling basis to confirm participation for the Spring 2026
			semester.
		</P>
	</div>
	<div
		class="items-center justify-center space-y-4 sm:flex sm:space-y-0 sm:space-x-4 rtl:space-x-reverse"
	>
		<Button
			pill
			href="https://pingpong.hks.harvard.edu/application"
			rel="noopener noreferrer"
			target="_blank"
			class="inline-flex items-center justify-center bg-blue-dark-40 px-5 text-lg font-medium text-white shadow-md hover:bg-blue-dark-50"
		>
			<span class="ms-3 w-full">Confirm your eligibility to participate</span>
			<ArrowRightOutline class="ms-2 h-6 w-6" />
		</Button>
	</div>

	<PingPongEduAccessCarousel />

	<Card padding="none" size="xl" class="grid md:grid-cols-2">
		<figure
			class="flex flex-col items-start justify-start rounded-t-lg border-b border-gray-200 bg-white text-start text-gray-900 md:col-span-2 dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="mt-4 mb-3 ml-5 text-2xl font-extrabold">
				Quick Facts about PingPong Educational Access
			</h3>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-t-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 md:rounded-t-none md:rounded-tl-lg md:border-e dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">Benefits for instructors</h3>
			<ol class="ml-7 list-disc font-light">
				<li class="my-2">
					Access to a highly customizable, multilingual tool that instructors can easily tailor to
					their syllabus and assignments.
				</li>
				<li class="my-2">
					Financial honorarium for engagement ($1,000 USD upon completing the study).
				</li>
				<li class="my-2">The possibility of improved student learning outcomes.</li>
				<li class="my-2">
					Optional short trainings to learn how to effectively use PingPong and similar AI tools.
				</li>
			</ol>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-tr-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">Benefits for students</h3>
			<ol class="ml-7 list-disc font-light">
				<li class="my-2">
					Free access to PingPong, a multilingual AI chatbot designed specifically for educational
					settings.
				</li>
				<li class="my-2">
					The possibility of improved learning outcomes due to access to the tool.
				</li>
			</ol>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-t-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 md:rounded-t-none md:rounded-tl-lg md:border-e dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">Who can participate?</h3>
			<ol class="ml-7 list-disc font-light">
				<li class="my-2">
					Instructors at two- and four-year colleges, especially those teaching math, economics,
					statistics and or computer science.
				</li>
			</ol>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-tr-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">Why should you participate?</h3>
			<ol class="ml-7 list-disc font-light">
				<li class="my-2">Help shape the future of education.</li>
				<li class="my-2">Get access to cutting-edge learning tools.</li>
				<li class="my-2">
					Gain insights on student learning via access to de-identified student interactions with
					the tool.
				</li>
			</ol>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-t-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 md:rounded-t-none md:rounded-tl-lg md:border-e dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">What does participation entail?</h3>
			<ol class="ml-7 list-disc font-light">
				<li class="my-2">
					Agree that you and your students will not use other generative AI teaching tools — like
					ChatGPT — for the duration of the study.
				</li>
				<li class="my-2">
					Administer a short (15 minute) online assessment for students at the beginning of the
					semester, as a part of your course's required assignments.
				</li>
				<li class="my-2">
					Integrate PingPong into your courses if you are randomly selected to be in the treatment
					group.
				</li>
				<li class="my-2">
					Administer a short (15 minute) online assessment for students at the end of the semester,
					as a part of your course's required assignments.
				</li>
			</ol>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-tr-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">Who is developing PingPong?</h3>
			<span class="my-2 font-light">
				PingPong was developed by the <a
					href="https://policylab.hks.harvard.edu/"
					rel="noopener noreferrer"
					class="underline"
					target="_blank">Computational Policy Lab at Harvard University</a
				>. The lab uses technology to tackle pressing societal issues, including in education. We
				believe that this technology can be particularly powerful at levelling educational
				inequalities. With this study, we aim to understand how artificial intelligence can help
				improve teaching and learning.
			</span>
		</figure>
		<figure
			class="flex flex-col items-start justify-start rounded-b-lg rounded-bl-lg border-b border-gray-200 bg-white p-8 text-start text-gray-900 md:col-span-2 dark:border-gray-700 dark:bg-gray-800"
		>
			<h3 class="text-lg font-semibold">How can I participate?</h3>
			<span class="my-2 font-light">
				Complete <a
					href="https://pingpong.hks.harvard.edu/application"
					rel="noopener noreferrer"
					class="underline"
					target="_blank">this short (15-minute) survey</a
				>
				to confirm your eligibility. Our team will be in touch on a rolling basis to confirm participation
				for the Spring 2026 semester.
				<br /><br />For further questions, please contact
				<a
					href="mailto:support@pingpong-hks.atlassian.net"
					rel="noopener noreferrer"
					class="underline"
					target="_blank">support@pingpong-hks.atlassian.net</a
				>.
			</span>
		</figure>
	</Card>

	<h3 class="mt-8 ml-5 text-2xl font-extrabold">FAQ for Instructors</h3>
	<ol class="ml-7 list-disc font-light">
		<li class="my-2">
			<h4 class="text-lg font-semibold">
				Has this study received Institutional Review Board (IRB) approval?
			</h4>
			Yes, the study has been reviewed and received an exempt determination from the Harvard University-Area
			IRB. If you need a copy of the approval letter or additional documentation, please contact us directly
			at
			<a
				href="mailto:support@pingpong-hks.atlassian.net"
				rel="noopener noreferrer"
				class="underline"
				target="_blank">support@pingpong-hks.atlassian.net</a
			>.
		</li>
		<li class="my-2">
			<h4 class="text-lg font-semibold">
				What does the study require from instructors and students?
			</h4>
			<ol class="ml-7 list-disc font-light">
				<li class="my-2">
					Instructors will integrate a brief baseline and end-of-semester assessment into their
					courses. Our team will provide instructors with initial versions of these assessments,
					which will assess general subject-matter knowledge. These activities can be completed in
					or outside class at the instructor's discretion.
				</li>
				<li class="my-2">
					When completing the assessment, students will participate in an informed consent process
					to decide whether their de-identified data can be used in the study. Data will be
					anonymized and securely stored to protect student privacy. Students who do not consent to
					study participation will still receive access to PingPong (see below for access timing
					details).
				</li>
				<li class="my-2">
					If admitted to the study, you agree that you and your students will not use other
					generative AI teaching tools — like ChatGPT — for the duration of the study.
				</li>
			</ol>
		</li>
		<li class="my-2">
			<h4 class="text-lg font-semibold">How is student data used and protected?</h4>
			Only de-identified data will be accessed by the research team. Instructors may choose to use identifiable
			assessment data for course purposes, but student consent decisions are confidential and will not
			affect their course participation or grades.
		</li>
		<li class="my-2">
			<h4 class="text-lg font-semibold">
				Will instructors and students receive free access to PingPong after the study?
			</h4>
			Yes, after the study concludes, all instructors and students—both those in the treatment group and
			the control group—will receive free access for the following semester. (During the study, instructors
			and students in the treatment group will have free access to PingPong.)
		</li>
		<li class="my-2">
			<h4 class="text-lg font-semibold">
				Does the study accommodate both in-person and online courses?
			</h4>
			Yes, both in-person and online courses are eligible for participation. If you teach a mix of formats,
			you can still participate.
		</li>
		<li class="my-2">
			<h4 class="text-lg font-semibold">
				Are dual credit courses offered with high schools eligible?
			</h4>
			Yes, dual credit courses may be eligible, but all student participants must be over 18 years old
			and provide consent to participate in the study.
		</li>
	</ol>
</div>
