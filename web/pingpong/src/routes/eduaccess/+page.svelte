<script lang="ts">
  import { Button, Card, Heading, P } from 'flowbite-svelte';
  import { ArrowRightOutline } from 'flowbite-svelte-icons';
  import PingPongEduAccessCarousel from '$lib/components/PingPongEduAccessCarousel.svelte';
</script>

<div class="px-4 py-8 md:px-12 md:py-12 flex flex-col gap-4 about h-full overflow-y-auto">
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
      large-scale study. Initial access to PingPong will be provided to half of the participating
      instructors, with access provided to all instructors in the following semester. An
      <b>honorarium of $1,000</b> will be provided to all participating instructors.</P
    >
    <P class="mt-4"
      >The study is underway for the spring 2025 semester and we are <b
        >now considering applications for summer and fall 2025 courses</b
      >. To participate, complete a short (5-question) survey to <b>confirm your eligibility</b>.
      Our team will be in touch in late spring 2025 to confirm summer course participation.
    </P>
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

  <Card padding="none" size="xl" class="grid md:grid-cols-2">
    <figure
      class="flex flex-col md:col-span-2 justify-start items-start text-start bg-white text-gray-900 border-b rounded-t-lg border-gray-200 dark:bg-gray-800 dark:border-gray-700"
    >
      <h3 class="mt-4 ml-5 mb-3 text-2xl font-extrabold">
        Quick Facts about PingPong Educational Access
      </h3>
    </figure>
    <figure
      class="flex flex-col justify-start items-start p-8 text-start bg-white text-gray-900 rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e dark:bg-gray-800 dark:border-gray-700"
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
      class="flex flex-col justify-start items-start p-8 text-start bg-white text-gray-900 rounded-tr-lg border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700"
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
      class="flex flex-col justify-start items-start p-8 text-start bg-white text-gray-900 rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e dark:bg-gray-800 dark:border-gray-700"
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
      class="flex flex-col justify-start items-start p-8 text-start bg-white text-gray-900 rounded-tr-lg border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700"
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
      class="flex flex-col justify-start items-start p-8 text-start bg-white text-gray-900 rounded-t-lg border-b border-gray-200 md:rounded-t-none md:rounded-tl-lg md:border-e dark:bg-gray-800 dark:border-gray-700"
    >
      <h3 class="text-lg font-semibold">What does participation entail?</h3>
      <ol class="list-disc ml-7 font-light">
        <li class="my-2">
          Administer a short (15 minute) online assessment for students at the beginning of the
          semester, as a part of your course's required assignments.
        </li>
        <li class="my-2">
          Administer a short (15 minute) online assessment for students at the end of the semester,
          as a part of your course's required assignments.
        </li>
        <li class="my-2">
          Optional: Work with our team to design the assessments and customize PingPong to your
          class.
        </li>
      </ol>
    </figure>
    <figure
      class="flex flex-col justify-start items-start p-8 text-start bg-white text-gray-900 rounded-tr-lg border-b border-gray-200 dark:bg-gray-800 dark:border-gray-700"
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
      class="flex flex-col md:col-span-2 justify-start items-start p-8 text-start bg-white text-gray-900 rounded-bl-lg border-b rounded-b-lg border-gray-200 dark:bg-gray-800 dark:border-gray-700"
    >
      <h3 class="text-lg font-semibold">How can I participate?</h3>
      <span class="my-2 font-light">
        Complete <a
          href="https://harvard.az1.qualtrics.com/jfe/form/SV_3xRMxp1g44nnjka"
          rel="noopener noreferrer"
          class="underline"
          target="_blank">this short (5-question) survey</a
        >
        to indicate your interest. Our team will follow up to confirm eligibility by the end of the Fall
        2024 semester.<br /><br />For further questions, please contact
        <a
          href="mailto:pingpongedu@hks.harvard.edu"
          rel="noopener noreferrer"
          class="underline"
          target="_blank">pingpongedu@hks.harvard.edu</a
        >.
      </span>
    </figure>
  </Card>

  <h3 class="mt-8 ml-5 text-2xl font-extrabold">FAQ for Instructors</h3>
  <ol class="list-disc ml-7 font-light">
    <li class="my-2">
      <h4 class="text-lg font-semibold">
        Has this study received Institutional Review Board (IRB) approval?
      </h4>
      Yes, the study has been reviewed and received an exempt determination from the Harvard University-Area
      IRB. If you need a copy of the approval letter or additional documentation, please contact us directly
      at
      <a
        href="mailto:pingpongedu@hks.harvard.edu"
        rel="noopener noreferrer"
        class="underline"
        target="_blank">pingpongedu@hks.harvard.edu</a
      >.
    </li>
    <li class="my-2">
      <h4 class="text-lg font-semibold">
        What does the study require from instructors and students?
      </h4>
      <ol class="list-disc ml-7 font-light">
        <li class="my-2">
          Instructors will integrate a brief baseline and end-of-semester assessment into their
          courses. Our team will provide instructors with initial versions of these assessments,
          which will assess general subject-matter knowledge. Instructors will have the option to
          customize further for their specific classes, or administer as-is. These activities can be
          completed in or outside class at the instructor's discretion.
        </li>
        <li class="my-2">
          When completing the assessment, students will participate in an informed consent process
          to decide whether their de-identified data can be used in the study. Data will be
          anonymized and securely stored to protect student privacy. Students who do not consent to
          study participation will still receive access to PingPong (see below for access timing
          details).
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
      Yes, after the study concludes, all instructors and students—both those in the treatment group
      and the control group—will receive free access for the following semester (Fall 2025). (During
      the study, instructors and students in the treatment group will have free access to PingPong.)
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
