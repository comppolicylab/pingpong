<script lang="ts">
  import {Select, Label, Input, GradientButton, Textarea, Heading, P} from "flowbite-svelte";

  export let data;
  export let form;

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
    <Heading tag="h3">What is it?</Heading>
    <P>
      PingPong is a tool for using large language models in a pedagogical setting.
    </P>
    <P>This app lets you create GPT models that are customized with documents relevant to your course or workshop, and share them with a group of students.</P>
    <P>
      PingPong is built on top of <a href="https://openai.com/gpt-4" rel="noopener noreferrer" target="_blank">GPT-4</a>, a large language model developed by <a href="https://openai.com" rel="noopener noreffer" target="_blank">OpenAI</a>.
    </P>
  </div>

  <div>
    <Heading tag="h3">Who built it?</Heading>
    <P>
      This app was developed by the <a href="https://policylab.hks.harvard.edu" rel="noopener noreferrer" target="_blank">Computational Policy Lab</a> at the <a href="https://hks.harvard.edu" rel="noopener noreferrer" target="_blank">Harvard Kennedy School</a>.
    </P>
  </div>

  <div>
    <Heading tag="h3">How can I get help?</Heading>
      <P>
        {@html data.supportInfo.blurb}
      </P>
      {#if data.supportInfo.can_post}
        <div>
          <P>
        You can also send us a quick message with this form and we will try to get back to you soon!
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

<style lang="css">
  :global(.about a) {
    color: #1a202c;
    text-decoration: underline;
  }
</style>
