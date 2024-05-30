<script lang="ts">
  import { Select, Label, Input, GradientButton, Textarea, Heading, P } from 'flowbite-svelte';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import { writable } from 'svelte/store';
  import { happyToast, sadToast } from '$lib/toast.js';
  import * as api from '$lib/api';

  export let data;

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
  <div>
    <Heading tag="h2">About PingPong</Heading>
  </div>

  <div>
    <Heading tag="h3" class="my-4">What is it?</Heading>
    <P>PingPong is a tool for using large language models in a pedagogical setting.</P>
    <P
      >This app lets you create GPT models that are customized with documents relevant to your
      course or workshop, and share them with a group of students.</P
    >
    <P>
      PingPong is built on top of <a
        href="https://openai.com/gpt-4"
        rel="noopener noreferrer"
        target="_blank">GPT-4</a
      >, a large language model developed by
      <a href="https://openai.com" rel="noopener noreffer" target="_blank">OpenAI</a>.
    </P>
  </div>

  <div>
    <Heading tag="h3" class="my-4">What kinds of data do you collect?</Heading>
    <P>
      We collect usage information to monitor abuse, maintain our infrastructure, and improve the
      app. Our technical team and app admins have access to the information described below.
    </P>
    <P>All data we collect may be stored indefinitely.</P>
    <P class="m-4 p-2 bg-amber-100 rounded" color="text-gray-600">
      Please note we do not share any of this information with third parties.
    </P>
    <ol class="list-decimal mx-24">
      <li class="my-2">
        Our developers collect and analyze anonymized usage information, such as number of users,
        request / token volume, and error rates.
      </li>
      <li class="my-2">
        We automatically log errors in the app to <a
          href="https://sentry.io"
          rel="noopener noreferrer"
          target="_blank">Sentry</a
        >, which our developers have access to. These logs do not contain any identifiable
        information about any user who might have triggered the error.
      </li>
      <li class="my-2">
        The teaching team of a class can view all threads in that class, including the content of
        messages and the users participating in them.
      </li>
      <li class="my-2">
        Anyone with access to the OpenAI API key used in a class is able to view the content of all
        messages and files used in that class. The people with access to the API key may or may not
        be PingPong users; we cannot stop the API key owner from sharing the key with others outside
        of PingPong.
      </li>
      <li class="my-2">
        Documents uploaded to the app are stored on OpenAI's servers, not our own. We are able to
        delete these files as necessary.
      </li>
    </ol>
  </div>

  <div>
    <Heading tag="h3" class="my-4">Who built it?</Heading>
    <P>
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
    <P>Here are a few disclosures, rules, and disclaimers about this app:</P>
    <ol class="list-decimal mx-24">
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
      <li class="my-2">
        This is <strong>not</strong> a confidential or secure app. Do not use it to process sensitive
        information.
      </li>
    </ol>
  </div>

  <div>
    <Heading tag="h3" class="my-4">How can I get help?</Heading>
    <P>
      <Sanitize html={data.supportInfo.blurb} />
    </P>
    {#if data.supportInfo.can_post}
      <div>
        <P>
          You can send us a message with the following form and we will try to get back to you soon!
        </P>
        <P class="m-4 p-2 bg-amber-100 rounded" color="text-gray-600">
          Please note that if you choose to share your personal information (name, email) with us,
          we will only use it if we need to contact you regarding your message. We do not store this
          information with our other app data and will not share it with anyone else.
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
