<script lang="ts">
  import { Heading, P, Modal, A } from 'flowbite-svelte';
  import PingPongDemoCarousel from '$lib/components/PingPongDemoCarousel.svelte';

  export let nonAuthed: boolean;
  export let linksOpenInNewTab: boolean = false;

  const year = new Date().getFullYear();
  let acknowledgementsModal = false;
</script>

<div class="flex flex-col gap-8 about h-full overflow-y-auto">
  <slot name="header" />
  <div class="text-center px-12 pt-12">
    <Heading tag="h2" class="mt-4 mb-6" customSize="text-4xl font-extrabold md:text-5xl lg:text-6xl"
      >{#if nonAuthed}Welcome to{:else}About{/if}
      <span class="bg-gradient-to-t from-orange-dark to-orange text-transparent bg-clip-text"
        >PingPong</span
      ></Heading
    >
  </div>
  <div class="px-12">
    <Heading tag="h3" class="my-4">What is it?</Heading>
    <P class="ml-0.5 mt-4"
      >PingPong is a platform for using large language models (LLMs) for teaching and learning. You
      can use it to create and share custom bots for specific tasks, like serving as a virtual
      teaching assistant with access to course documents. PingPong has been used by thousands of
      students in dozens of colleges across the United States.</P
    >
    <P class="ml-0.5 mt-4"
      >PingPong is built on top of OpenAI's latest text- and voice-based models. We've designed the
      platform from the ground up with teachers and students in mind. For example:</P
    >
    <ul class="list-disc ml-7">
      <li class="my-2">
        Each week, instructors get an AI-generated summary of how students are using the bots in
        their courses, which can help to tailor class content. Instructors can also view individual,
        de-identified chats, to gain further insights.
      </li>
      <li class="my-2">
        We make it straightforward to create real-time, voice-based bots. These bots can be used,
        for example, to quiz students on their understanding of the course material.
      </li>
      <li class="my-2">
        Bot instructions can be randomized, both to facilitate experimentation and to ensure
        variation across interactions (e.g., so bot-administered "quizzes" are not all the same).
      </li>
      <li class="my-2">
        None of the information entered on PingPong will be used by OpenAI to train their models,
        ensuring user data are kept private.
      </li>
      <li class="my-2">
        PingPong is integrated into Canvas, making it easy for faculty and students to get up and
        running quickly.
      </li>
    </ul>
  </div>
  {#if nonAuthed}
    <div class="px-14"><PingPongDemoCarousel /></div>
  {/if}
  <div class="px-12">
    <Heading tag="h3" class="my-4">What kinds of data do you collect?</Heading>
    <P class="ml-0.5 mt-4">
      Please read our <a
        href="/privacy-policy"
        class="underline"
        rel="noopener noreferrer"
        target={linksOpenInNewTab ? '_blank' : undefined}>privacy policy</a
      > to learn about what information we collect and how we keep it safe.
    </P>
  </div>

  <div class="px-12">
    <Heading tag="h3" class="my-4">Who built it?</Heading>
    <P class="ml-0.5 mt-4">
      This app was developed by the <a
        href="https://policylab.hks.harvard.edu"
        class="underline"
        rel="noopener noreferrer"
        target="_blank">Computational Policy Lab</a
      >
      at the
      <a href="https://hks.harvard.edu" class="underline" rel="noopener noreferrer" target="_blank"
        >Harvard Kennedy School</a
      >.
    </P>
  </div>

  <div class="px-12">
    <Heading tag="h3" class="my-4">What else should I know?</Heading>
    <P class="ml-0.5 mt-4">Here are a few disclosures, rules, and disclaimers about this app:</P>
    <ol class="list-decimal ml-7">
      <li class="my-2">
        We are monitoring the app for signs of abuse and will take action if we see it.
      </li>
      <li class="my-2">
        "Abuse" includes prompt injection, or any activity that could compromise the performance or
        integrity of our app, or anything else inconsistent with the app's intended use.
      </li>
      <li class="my-2">
        You must adhere to <a
          href="https://policy.security.harvard.edu/policies"
          rel="noopener noreferrer"
          class="underline"
          target="_blank">Harvard's Information Security Policy</a
        > while using this app.
      </li>
      <li class="my-2">
        This is an experimental, beta version of the app. We are actively developing this project,
        and while we are doing our best to ensure uptime and reliability, we make no guarantees at
        this time!
      </li>
    </ol>
  </div>

  <slot name="footer" />
  <div class="flex flex-col gap-8 bg-blue-dark-40 p-8 w-full">
    <div class="flex flex-row gap-2 justify-evenly px-12 items-center">
      <div class="w-48">
        <a href="https://shorensteincenter.org/" rel="noopener noreferrer" target="_blank">
          <img
            src="/HKSlogo_shorenstein_transparent-1.png"
            alt="Harvard Kennedy School - Shorenstein Center logo"
          />
        </a>
      </div>
      <div>
        <a
          href="https://policylab.hks.harvard.edu"
          class="flex flex-row gap-2 items-center"
          rel="noopener noreferrer"
          target="_blank"
        >
          <img
            src="/cpl_logo_white.svg"
            style="height: 1.2rem"
            alt="Computational Policy Lab logo"
          />
          <span class="font-mono text-gray-100 text-sm">COMPUTATIONAL POLICY LAB</span>
        </a>
      </div>
    </div>
    <P class="text-xs w-full text-center text-gray-100 mt-4"
      >All content &copy; {year} Computational Policy Lab. All rights reserved. <A
        class="underline"
        on:click={() => {
          acknowledgementsModal = true;
        }}>Acknowledgements</A
      ></P
    >
  </div>
</div>

<Modal
  bind:open={acknowledgementsModal}
  autoclose
  outsideclose
  title="Acknowledgements"
  size="lg"
  classHeader="text-base"
>
  <div class="flex flex-col gap-4 text-sm">
    <p>
      Portions of this PingPong Software may utilize the following copyrighted material, the use of
      which is hereby acknowledged.
    </p>
    <div class="flex flex-col gap-2">
      <p class="font-semibold text-base">OpenAI ( openai-realtime-console )</p>
      <div>MIT License</div>

      <div>Copyright &copy; 2024 OpenAI</div>

      <div>
        Permission is hereby granted, free of charge, to any person obtaining a copy of this
        software and associated documentation files (the "Software"), to deal in the Software
        without restriction, including without limitation the rights to use, copy, modify, merge,
        publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
        to whom the Software is furnished to do so, subject to the following conditions:
      </div>

      <div>
        The above copyright notice and this permission notice shall be included in all copies or
        substantial portions of the Software.
      </div>

      <div>
        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
        INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
        PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
        FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
        OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
        DEALINGS IN THE SOFTWARE.
      </div>
    </div>
    <div class="flex flex-col gap-2">
      <p class="font-semibold text-base">OpenAI ( openai-realtime-api-beta )</p>
      <div>MIT License</div>

      <div>Copyright &copy; 2024 OpenAI</div>

      <div>
        Permission is hereby granted, free of charge, to any person obtaining a copy of this
        software and associated documentation files (the "Software"), to deal in the Software
        without restriction, including without limitation the rights to use, copy, modify, merge,
        publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
        to whom the Software is furnished to do so, subject to the following conditions:
      </div>

      <div>
        The above copyright notice and this permission notice shall be included in all copies or
        substantial portions of the Software.
      </div>

      <div>
        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
        INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
        PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
        FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
        OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
        DEALINGS IN THE SOFTWARE.
      </div>
    </div>
  </div>
</Modal>
