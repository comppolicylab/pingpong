<script lang="ts">
  import { Button, Card, Heading, P } from 'flowbite-svelte';
  import { ArrowRightOutline } from 'flowbite-svelte-icons';
  import PingPongDemoCarousel from '$lib/components/PingPongDemoCarousel.svelte';
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
      >Give your students free access to a custom version of ChatGPT designed to improve teaching
      and learning.
    </P>
  </div>
  <div class="mx-7 mb-2">
    <P class="leading-6 mt-4"
      >We are seeking instructors at two- and four-year colleges, especially those teaching math,
      economics, statistics and or computer science to participate in a large-scale study to assess
      the benefits of generative AI on student learning. An honorarium will be provided to
      participating instructors.</P
    >
    <P class="mt-4">To participate, complete a short (6-question) survey:</P>
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

  <PingPongDemoCarousel />

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
          <li class="my-2">Additional support in answering student questions.</li>
          <li class="my-2">
            Access to a highly customizable, multilingual tool which provides analytics on students'
            use.
          </li>
          <li class="my-2">Financial honorarium for engagement.</li>
          <li class="my-2">The possibility of improved student learning outcomes.</li>
          <li class="my-2">Training for instructors on how to best leverage these tools.</li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white border-t border-b border-gray-200 md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Benefits for students</h3>
        <ol class="list-disc ml-7 font-light">
          <li class="my-2">
            Free access to a multilingual AI chatbot, designed specifically for educational
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
          <li class="my-2">Instructors at two- and four-year colleges.</li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Why should you participate?</h3>
        <ol class="list-disc ml-7 font-light">
          <li class="my-2">Help shape the education of the future.</li>
          <li class="my-2">Get access to cutting-edge learning tools.</li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">What does participation entail?</h3>
        <ol class="list-disc ml-7 font-light">
          <li class="my-2">
            Short & anonymous (15-minute) pre-study assessment exam for students.
          </li>
          <li class="my-2">
            One semester access to an AI chatbot that is customized to serve as a tutor for students
            completing a given course.
          </li>
          <li class="my-2">
            Short & anonymous (15-minute) post-study assessment exam for students.
          </li>
        </ol>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">How does Education Access work?</h3>
        <span class="my-2 font-light">
          We have developed an AI chatbot based on leading commercial LLM technology that has
          guardrails to safeguard learning and to individualize it for specific courses. We plan on
          randomly assigning access to the platform to participating instructors and their classes
          in the academic year of 2024/2025.
        </span>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-bl-lg border-b border-gray-200 md:border-b-0 md:border-e text-gray-900"
      >
        <h3 class="text-lg font-semibold">Who is developing PingPong?</h3>
        <span class="my-2 font-light">
          The <a
            href="https://policylab.hks.harvard.edu/"
            rel="noopener noreferrer"
            class="underline"
            target="_blank">Computational Policy Lab at Harvard Kennedy School</a
          > is using technology to tackle pressing societal issues, including in education. We believe
          that this technology can be particularly powerful at levelling educational inequalities at
          colleges with limited resources. With this study, we aim to understand how artificial intelligence
          can help improve teaching and learning.
        </span>
      </figure>
      <figure
        class="flex flex-col justify-start items-start p-8 text-start bg-white rounded-b-lg border-gray-200 md:rounded-br-lg text-gray-900"
      >
        <h3 class="text-lg font-semibold">How can I participate?</h3>
        <span class="my-2 font-light">
          Complete <a
            href="https://harvard.az1.qualtrics.com/jfe/form/SV_3xRMxp1g44nnjka"
            rel="noopener noreferrer"
            class="underline"
            target="_blank">this short (6-question) survey</a
          >.<br /><br />For further information, please contact
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
