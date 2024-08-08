<script lang="ts">
  import { Select, Label, Input, GradientButton, Textarea, Heading, P } from 'flowbite-svelte';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import { writable } from 'svelte/store';
  import { happyToast, sadToast } from '$lib/toast.js';
  import * as api from '$lib/api';
  import PingPongDemoCarousel from '$lib/components/PingPongDemoCarousel.svelte';

  export let data;

  $: nonAuthed = data.isPublicPage && !data?.me?.user;

  const year = new Date().getFullYear();

  const categories = [
    { value: 'other', name: 'Not sure!' },
    { value: 'bug', name: 'Bug Report' },
    { value: 'feature', name: 'Feature request' },
    { value: 'question', name: 'Question' }
  ];

  const loading = writable(false);
  const submitForm = async (evt: SubmitEvent) => {
    evt.preventDefault();
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const message = d.message?.toString();
    if (!message) {
      $loading = false;
      return sadToast('Message is required');
    }

    const data = {
      message: message,
      email: d.email?.toString(),
      name: d.name?.toString(),
      category: d.category?.toString()
    };

    const result = await api.postSupportRequest(fetch, data);
    if (result.$status < 300) {
      $loading = false;
      form.reset();
      happyToast('Your message has been sent, thanks for the feedback!');
    } else {
      $loading = false;
      sadToast('There was an error sending your message, please try again later.');
    }
  };
</script>

<div class="px-12 py-12 flex flex-col gap-8 about h-full overflow-y-auto">
  <div class="text-center">
    <Heading tag="h2" class="mt-4 mb-6" customSize="text-4xl font-extrabold md:text-5xl lg:text-6xl"
      >{#if nonAuthed}Welcome to{:else}About{/if}
      <span class="bg-gradient-to-t from-orange-dark to-orange text-transparent bg-clip-text"
        >PingPong</span
      ></Heading
    >
  </div>
  <div>
    <Heading tag="h3" class="my-4">What is it?</Heading>
    <P class="ml-0.5"
      >PingPong is a tool for using large language models (LLMs) for teaching and learning. You can
      use it to create and share custom bots for specific tasks, like serving as a virtual teaching
      assistant with access to course documents.</P
    >
    <P class="ml-0.5"
      >PingPong is built on top of <a
        href="https://openai.com/index/hello-gpt-4o/"
        rel="noopener noreferrer"
        target="_blank">GPT-4o</a
      >, a large language model developed by
      <a href="https://openai.com" rel="noopener noreffer" target="_blank">OpenAI</a>. But there are
      several advantages of using PingPong over ChatGPT. First, moderators can view de-identified
      chats, which helps instructors understand how their students are using the tool and
      potentially tailor class content accordingly. Second, none of the information entered on
      PingPong will be used by OpenAI to train their models, ensuring user data is kept private.
      Finally, PingPong is integrated into Canvas, making it easy for faculty and students to get up
      and running quickly.</P
    >
  </div>
  {#if nonAuthed}
    <PingPongDemoCarousel />
  {/if}
  <div>
    <Heading tag="h3" class="my-4">What kinds of data do you collect?</Heading>
    <P class="ml-0.5">
      Please read our <a href="/privacy-policy" rel="noopener noreferrer">privacy policy</a> to learn
      about what information we collect and how we keep it safe.
    </P>
  </div>

  <div>
    <Heading tag="h3" class="my-4">Who built it?</Heading>
    <P class="ml-0.5">
      This app was developed by the <a
        href="https://policylab.hks.harvard.edu"
        rel="noopener noreferrer"
        target="_blank">Computational Policy Lab</a
      >
      at the
      <a href="https://hks.harvard.edu" rel="noopener noreferrer" target="_blank"
        >Harvard Kennedy School</a
      >.
    </P>
  </div>

  <div>
    <Heading tag="h3" class="my-4">What else should I know?</Heading>
    <P class="ml-0.5">Here are a few disclosures, rules, and disclaimers about this app:</P>
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

  {#if !nonAuthed}
    <div>
      <Heading tag="h3" class="my-4">How can I get help?</Heading>
      <P class="ml-0.5">
        <Sanitize html={data.supportInfo.blurb} />
      </P>
      {#if data.supportInfo.can_post}
        <div>
          <P class="ml-0.5">
            You can send us a message with the following form and we will try to get back to you
            soon!
          </P>
          <P class="m-4 p-2 bg-amber-100 rounded" color="text-gray-600">
            Please note that if you choose to share your personal information (name, email) with us,
            we will only use it if we need to contact you regarding your message. We do not store
            this information with our other app data and will not share it with anyone else.
          </P>
          <div class="mt-6">
            <form on:submit={submitForm}>
              <div class="flex flex-col gap-4">
                <div class="flex flex-col gap-2">
                  <Label for="name">Name (optional)</Label>
                  <Input type="text" name="name" id="name" placeholder="Your name" />
                </div>
                <div class="flex flex-col gap-2">
                  <Label for="email">Email (optional)</Label>
                  <Input type="email" name="email" id="email" placeholder="Your email" />
                </div>
                <div class="flex flex-col gap-2">
                  <Label for="category">Category (optional)</Label>
                  <Select name="category" items={categories} />
                </div>
                <div class="flex flex-col gap-2">
                  <Label for="message">Message (max 500 characters)</Label>
                  <Textarea
                    maxlength="500"
                    name="message"
                    id="message"
                    placeholder="Your message"
                    rows="5"
                  />
                </div>
                <div class="flex flex-col gap-2 mx-auto">
                  <GradientButton class="w-20" type="submit" disabled={$loading} color="cyanToBlue"
                    >Send</GradientButton
                  >
                </div>
              </div>
            </form>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<div class="flex flex-col gap-8 bg-slate-500 p-8">
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
        <img src="/cpl_logo_white.svg" style="height: 1.2rem" alt="Computational Policy Lab logo" />
        <span class="font-mono text-gray-100 text-sm">COMPUTATIONAL POLICY LAB</span>
      </a>
    </div>
  </div>
  <P class="text-xs w-full text-center text-gray-100"
    >All content &copy; {year} Computational Policy Lab. All rights reserved.</P
  >
</div>

<style lang="css">
  :global(.about a) {
    color: #1a202c;
    text-decoration: underline;
  }
  :global(.about p) {
    margin-top: 1rem;
  }
</style>
