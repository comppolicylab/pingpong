<script lang="ts">
  import { Button, Card, Heading, P } from 'flowbite-svelte';
  import { ArrowRightOutline } from 'flowbite-svelte-icons';
  import PingPongEduAccessCarousel from '$lib/components/PingPongEduAccessCarousel.svelte';
</script>

<div class="px-12 py-12 flex flex-col gap-4 about h-full overflow-y-auto">
  <div class="flex flex-col text-center min-w-full">
    <Heading tag="h2" class="mt-4 mb-2" customSize="text-4xl font-extrabold md:text-5xl lg:text-6xl"
      ><span
        class="bg-gradient-to-t from-blue-dark-50 to-blue-dark-30 text-transparent bg-clip-text"
        >Educational Access</span
      >
    </Heading>
    <P
      class="mt-4 text-xl text-gray-700 text-center lg:text-2xl sm:px-16 md:px-25 md:px-35 xl:px-48"
      >Participate in a study evaluating the impact of AI on student learning at two- and four-year
      colleges.
    </P>
  </div>
  <div class="mx-7 mb-2">
    <P class="leading-6 mt-4"
      ><b>PingPong</b> is an AI-powered virtual teaching assistant based on ChatGPT, developed by students
      and teachers at Harvard. PingPong is designed to help students with homework without giving them
      the answers, much like a human tutor. Our study aims to assess how PingPong and similar AI tools
      can improve education.</P
    >
    <P class="mt-4"
      >We are seeking instructors at <b>two- and four-year colleges</b>, especially those teaching
      math, economics, statistics and/or computer science, to participate in a randomized
      large-scale study in the <b>Spring 2025 semester</b>. Initial access to PingPong will be
      provided to half of the participating instructors, with access provided to all instructors in
      the following semester. An <b>honorarium</b> will be provided to all participating instructors.</P
    >
    <P class="mt-4"
      >To participate, complete a short (5-question) survey to <b
        >confirm your eligibility by November 25, 2024</b
      >:</P
    >
  </div>
  <div
    class="justify-center items-center space-y-4 sm:flex sm:space-y-0 sm:space-x-4 rtl:space-x-reverse"
  >
    <Button
      pill
      href="https://harvard.az1.qualtrics.com/jfe/form/SV_3xRMxp1g44nnjka"
      rel="noopener noreferrer"
      target="_blank"
      class="text-white inline-flex justify-center text-lg items-center px-5 font-medium text-lg bg-blue-dark-40 hover:bg-blue-dark-50 shadow-md"
    >
      <span class="w-full ms-3">Express your interest for PingPong Edu Access</span>
      <ArrowRightOutline class="w-6 h-6 ms-2" />
    </Button>
  </div>

  <PingPongEduAccessCarousel />

  <Card padding="none" size="xl" class="mt-10">
    <Heading tag="h3" class="mt-4 ml-5 mb-3" customSize="text-2xl font-extrabold"
      >Quick Facts about PingPong Educational Access
    </Heading>
    <div class="grid md:grid-cols-2">
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white border-b border-t border-gray-200 md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Benefits for instructors</h3>
        <ol class="list-disc ml-7 font-light">
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
        class="flex flex-col justify-start items-start p-8 text-start bg-white border-t border-b border-gray-200 md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Benefits for students</h3>
        <ol class="list-disc ml-7 font-light">
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
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Who can participate?</h3>
        <ol class="list-disc ml-7 font-light">
          <li class="my-2">
            Instructors at two- and four-year colleges, especially those teaching math, economics,
            statistics and or computer science.
          </li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Why should you participate?</h3>
        <ol class="list-disc ml-7 font-light">
          <li class="my-2">Help shape the future of education.</li>
          <li class="my-2">Get access to cutting-edge learning tools.</li>
          <li class="my-2">
            Gain insights on student learning via access to de-identified student interactions with
            the tool.
          </li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">What does participation entail?</h3>
        <ol class="list-disc ml-7 font-light">
          <li class="my-2">
            Administer a short (15 minute) online assessment for students at the beginning of the
            semester, as a part of your course’s required assignments.
          </li>
          <li class="my-2">
            Administer a short (15 minute) online assessment for students at the end of the
            semester, as a part of your course’s required assignments.
          </li>
          <li class="my-2">
            Optional: Work with our team to design the assessments and customize PingPong to your
            class.
          </li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
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
        class="flex flex-col col-span-2 justify-start items-start p-8 text-start bg-white rounded-bl-lg border-b border-gray-200 md:border-b-0 md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">How can I participate?</h3>
        <span class="my-2 font-light">
          Complete <a
            href="https://harvard.az1.qualtrics.com/jfe/form/SV_3xRMxp1g44nnjka"
            rel="noopener noreferrer"
            class="underline"
            target="_blank">this short (5-question) survey</a
          >
          to indicate your interest. Our team will follow up to confirm eligibility by the end of the
          Fall 2024 semester.<br /><br />For further questions, please contact
          <a
            href="mailto:pingpongedu@hks.harvard.edu"
            rel="noopener noreferrer"
            class="underline"
            target="_blank">pingpongedu@hks.harvard.edu</a
          >.
        </span>
      </figure>
    </div>
  </Card>
</div>
