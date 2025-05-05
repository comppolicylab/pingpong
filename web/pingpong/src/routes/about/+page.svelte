<script lang="ts">
  import { Select, Label, Input, Textarea, Heading, P, Button, Modal, A } from 'flowbite-svelte';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import { writable } from 'svelte/store';
  import { happyToast, sadToast } from '$lib/toast.js';
  import * as api from '$lib/api';
  import PingPongDemoCarousel from '$lib/components/PingPongDemoCarousel.svelte';
  import { ExclamationCircleOutline, LockSolid } from 'flowbite-svelte-icons';

  export let data;

  $: nonAuthed = data.isPublicPage && !data?.me?.user;

  const year = new Date().getFullYear();

  const categories = [
    { value: 'bug', name: 'Bug Report' },
    { value: 'feature', name: 'Feature Request' },
    { value: 'question', name: 'Question' },
    { value: 'other', name: 'Other' }
  ];

  const loading = writable(false);
  const modal = writable(false);
  let contactInfoModal = false;

  function waitForModalResponse(): Promise<boolean> {
    return new Promise((resolve) => {
      $modal = contactInfoModal;

      const unsubscribe = modal.subscribe((isOpen) => {
        if (!isOpen && contactInfoModal) {
          unsubscribe();
          contactInfoModal = false;
          resolve(false);
        }
      });

      handleModalConfirm = () => {
        unsubscribe();
        contactInfoModal = false;
        $modal = false;
        resolve(true);
      };

      handleModalCancel = () => {
        unsubscribe();
        contactInfoModal = false;
        $modal = false;
        resolve(false);
      };
    });
  }

  const handleSubmit = async (evt: SubmitEvent) => {
    evt.preventDefault();
    $loading = true;

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const message = d.message?.toString();
    if (!message) {
      $loading = false;
      return sadToast('Please type a message before sending.');
    }

    const category = d.category?.toString();
    if (!category) {
      $loading = false;
      return sadToast('Please select a feedback category.');
    }

    if (!d.email?.toString() && !d.name?.toString()) {
      $loading = false;
      contactInfoModal = true;
      const shouldProceed = await waitForModalResponse();
      if (!shouldProceed) return;
      $loading = true;
    }

    const data = {
      message: d.message?.toString(),
      email: d.email?.toString(),
      name: d.name?.toString(),
      category: d.category?.toString()
    };

    const result = await api.postSupportRequest(fetch, data);
    if (result.$status < 300) {
      form.reset();
      happyToast('Your message has been sent, thanks for the feedback!');
    } else {
      sadToast('There was an error sending your message, please try again later.');
    }
    $loading = false;
  };

  let handleModalConfirm: () => void;
  let handleModalCancel: () => void;
  let acknowledgementsModal = false;
</script>

<div class="flex flex-col gap-8 about h-full overflow-y-auto">
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
      Please read our <a href="/privacy-policy" class="underline" rel="noopener noreferrer"
        >privacy policy</a
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

  {#if !nonAuthed}
    <div class="px-12 pb-8 bg-white">
      <Heading tag="h3" class="my-4">How can I get help?</Heading>
      <P class="ml-0.5 mt-4">
        <Sanitize html={data.supportInfo.blurb} />
      </P>
      {#if data.supportInfo.can_post}
        <div>
          <P class="ml-0.5 mt-4">
            You can send us a message with the following form and we will try to get back to you
            soon! If you do not provide an email address, we will not be able to respond to your
            message.
          </P>
          <div
            class="flex col-span-2 items-center rounded-lg text-white bg-gradient-to-r from-red-900 to-red-700 border border-gradient-to-r from-red-800 to-red-600 p-4 my-3"
          >
            <ExclamationCircleOutline class="w-8 h-8 mr-3" />
            <span>
              Heads up: <span class="font-semibold"
                >This form is for app feedback and bug reports only.</span
              > If you have a question about your group or course, or can't access your group's assistants,
              please reach out to your teaching staff directly. We can't help with those kinds of questions
              here.
            </span>
          </div>
          <div
            class="flex col-span-2 items-center rounded-lg text-white bg-gradient-to-r from-gray-800 to-gray-600 border-gradient-to-r from-gray-800 to-gray-600 p-4"
          >
            <LockSolid class="w-8 h-8 mr-3" />
            <span>
              Please note that if you choose to share your personal information (name, email) with
              us, we will only use it if we need to contact you regarding your message. We do not
              store this information with our other app data and will not share it with anyone else.
            </span>
          </div>
          <div class="mt-6">
            <form on:submit={handleSubmit}>
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
                  <Label for="category">Category</Label>
                  <Select name="category" items={categories} />
                </div>
                <div class="flex flex-col gap-2">
                  <Label for="message">Message (max 500 characters)</Label>
                  <Textarea
                    maxlength={500}
                    name="message"
                    id="message"
                    placeholder="Your message"
                    rows={5}
                  />
                </div>
                <div class="flex flex-col gap-2 mx-auto">
                  <Button
                    pill
                    class="w-20 text-white inline-flex justify-center items-center px-5 bg-blue-dark-40 hover:bg-blue-dark-50 shadow-md"
                    type="submit"
                    disabled={$loading}>Send</Button
                  >
                </div>

                <Modal bind:open={contactInfoModal} size="xs" autoclose>
                  <div class="text-center px-2">
                    <ExclamationCircleOutline class="mx-auto mb-4 text-red-600 w-12 h-12" />
                    <h3 class="mb-5 text-xl text-gray-900 dark:text-white font-bold">
                      Send message without contact information?
                    </h3>
                    <p class="mb-5 text-sm text-gray-700 dark:text-gray-300">
                      You chose not to include your contact information with the support message you
                      are sending. We do not associate user information with support requests unless
                      you provide it to us.
                      <span class="font-bold"
                        >If you would like us to contact you about your specific support issue,
                        please include your contact information with your message.</span
                      >
                    </p>
                    <div class="flex justify-center gap-4">
                      <Button pill color="alternative" on:click={handleModalCancel}>Go back</Button>
                      <Button pill outline color="red" on:click={handleModalConfirm}
                        >Send without contact information</Button
                      >
                    </div>
                  </div>
                </Modal>
              </div>
            </form>
          </div>
        </div>
      {/if}
    </div>
  {/if}
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
