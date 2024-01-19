<script lang="ts">
  import {Hr, Select, Label, Input, GradientButton, Textarea, Heading, P} from "flowbite-svelte";

  export let data;
  export let form;

  const year = new Date().getFullYear();

  const categories = [
    {value: "other", name: "Not sure!"},
    {value: "bug", name: "Bug Report"},
    {value: "feature", name: "Feature request"},
    {value: "question", name: "Question"},
  ];
</script>
<div class="mx-12 my-12 flex flex-col gap-8 about">
  <div>
  <Heading tag="h2">About PingPong</Heading>
  </div>

  <div>
    <Heading tag="h3" class="my-4">What is it?</Heading>
    <P>
      PingPong is a tool for using large language models in a pedagogical setting.
    </P>
    <P>This app lets you create GPT models that are customized with documents relevant to your course or workshop, and share them with a group of students.</P>
    <P>
      PingPong is built on top of <a href="https://openai.com/gpt-4" rel="noopener noreferrer" target="_blank">GPT-4</a>, a large language model developed by <a href="https://openai.com" rel="noopener noreffer" target="_blank">OpenAI</a>.
    </P>
  </div>

  <div>
    <Heading tag="h3" class="my-4">What kind of data do you collect?</Heading>
    <P>
      We collect usage information to monitor abuse, maintain our infrastructure, and improve the app. Our technical team and app admins have access to the information described below.
    </P>
    <P class="m-4 p-2 bg-amber-100 rounded" color="text-gray-600">
      Please note we do not share any of this information with third parties.
    </P>
    <ol class="list-decimal">
      <li class="my-2">Our developers collect and analyze anonymized usage information, such as number of useres, request / token volume, and error rates.</li>
      <li class="my-2">We automatically log errors in the app to <a href="https://sentry.io" rel="noopener noreferrer" target="_blank">Sentry</a>, which our developers have access to. These logs do not contain any identifiable information about any user who might have triggered the error.</li>
      <li class="my-2">The teaching team of a class can view all threads in that class, including the content of messages and the users participating in them.</li>
      <li class="my-2">Anyone with access to the OpenAI API key used in a class is able to view the content of all messages and files used in that class. The people with access to the API key may or may not be PingPong users; we cannot stop the API key owner from sharing the key with others outside of PingPong.</li>
      <li class="my-2">Documents uploaded to the app are stored on OpenAI's servers, not our own. We are able to delete these files as necessary.</li>
    </ol>
    <P>These data will be retained for up to 12 months.</P>
  </div>

  <div>
    <Heading tag="h3" class="my-4">Who built it?</Heading>
    <P>
      This app was developed by the <a href="https://policylab.hks.harvard.edu" rel="noopener noreferrer" target="_blank">Computational Policy Lab</a> at the <a href="https://hks.harvard.edu" rel="noopener noreferrer" target="_blank">Harvard Kennedy School</a>.
    </P>
  </div>

  <div>
    <Heading tag="h3" class="my-4">What else should I know?</Heading>
    <P>Here are a few disclosures, rules, and disclaimers about this app:</P>
    <ol class="list-decimal">
      <li class="my-2">We are monitoring the app for signs of abuse and will take action if we see it.</li>
      <li class="my-2">"Abuse" includes prompt injection, or any activity that could compromise the performance or integrity of our app, or anything else inconsistent with the app's intended use.</li>
      <li class="my-2">You must adhere to <a href="https://policy.security.harvard.edu/policies" rel="noopener noreferrer" target="_blank">Harvard's Information Security Policy</a>.</li>
      <li class="my-2">This is an experimental, beta version of the app. We are actively developing this project, and while we are doing our best to ensure uptime and reliability, we make not guarantees at this time!</li>
      <li class="my-2">This is <strong>not</strong> a confidential or secure app. Do not use it to process sensitive information.</li>
    </ol>
  </div>

  <div>
    <Heading tag="h3" class="my-4">How can I get help?</Heading>
      <P>
        {@html data.supportInfo.blurb}
      </P>
      {#if data.supportInfo.can_post}
        <div>
          <P>
        You can also send us a quick message with this form and we will try to get back to you soon!
          </P>
          <P class="m-4 p-2 bg-amber-100 rounded" color="text-gray-600">
            Please note that if you choose to share your personal information (name, email) with us, we will only use it to respond to your message. We will not share it with anyone else.
          </P>
          <div class="mt-6">
          {#if form?.success}
            <P class="text-green-500">Your message has been sent, thanks for the feedback!</P>
          {:else if form?.error}
            <P class="text-red-500">There was an error sending your message, please try again later.</P>
          {/if}
          <form action="?/support" method="POST">
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
                <Label for="message">Message</Label>
                  <Textarea name="message" id="message" placeholder="Your message" rows="5" />
              </div>
              <div class="flex flex-col gap-2 mx-auto">
                <GradientButton class="w-20" type="submit" color="cyanToBlue">Send</GradientButton>
              </div>
            </div>
          </form>
          </div>
        </div>
      {/if}
  </div>
</div>

  <div class="flex flex-col gap-8 bg-slate-500 p-8">
    <div class="flex flex-row gap-2 justify-evenly px-12">
      <div class="w-48">
    <img src="/HKSlogo_shorenstein_transparent-1.png" alt="Harvard Kennedy School - Shorenstein Center logo" />
      </div>
    <div class="flex flex-row gap-2 items-center">
      <img src="/cpl_logo_white.svg" style="height: 1.2rem" alt="Computational Policy Lab logo">
      <span class="font-mono text-gray-100 text-sm">COMPUTATIONAL POLICY LAB</span>
    </div>
    </div>
  <P class="text-xs w-full text-center text-gray-100">All content &copy; {year} Computational Policy Lab. All rights reserved.</P>
  </div>

<style lang="css">
  :global(.about a) {
    color: #1a202c;
    text-decoration: underline;
  }
</style>
