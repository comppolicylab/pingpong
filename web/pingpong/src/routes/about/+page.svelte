<script lang="ts">
  import { Select, Label, Input, Textarea, Heading, P, Button, Modal } from 'flowbite-svelte';
  import Sanitize from '$lib/components/Sanitize.svelte';
  import { writable } from 'svelte/store';
  import { happyToast, sadToast } from '$lib/toast.js';
  import * as api from '$lib/api';
  import { ExclamationCircleOutline, InfoCircleSolid, LockSolid } from 'flowbite-svelte-icons';
  import AboutPage from '$lib/components/AboutPage.svelte';

  export let data;

  $: nonAuthed = data.isPublicPage && !data?.me?.user;
  $: openAllLinksInNewTab = data.openAllLinksInNewTab;
  $: hasNoGroups = !nonAuthed && data.classes?.length === 0;

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
</script>

<AboutPage {nonAuthed} linksOpenInNewTab={openAllLinksInNewTab}>
  <div class="px-12 pt-8" slot="header">
    {#if hasNoGroups}
      <div class="w-full rounded-lg border border-gray-300 bg-gray-100 p-6">
        <div class="flex items-start gap-4">
          <InfoCircleSolid class="w-6 h-6 text-gray-500 shrink-0 mt-0.5" />
          <div class="flex-1">
            <h5 class="text-lg font-semibold text-gray-900 mb-2">
              It's a little empty around here...
            </h5>
            <p class="text-md text-gray-600">
              You're not part of any PingPong groups yet. Ask your instructor or course
              administrator to add you to a group to get started. If you believe this is an error,
              please see the support information below for help.
            </p>
          </div>
        </div>
      </div>
    {/if}
  </div>
  <span slot="footer">
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
                store this information with our other app data and will not share it with anyone
                else.
              </span>
            </div>
            <div class="mt-6">
              <form onsubmit={handleSubmit}>
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
                        You chose not to include your contact information with the support message
                        you are sending. We do not associate user information with support requests
                        unless you provide it to us.
                        <span class="font-bold"
                          >If you would like us to contact you about your specific support issue,
                          please include your contact information with your message.</span
                        >
                      </p>
                      <div class="flex justify-center gap-4">
                        <Button pill color="alternative" onclick={handleModalCancel}>Go back</Button
                        >
                        <Button pill outline color="red" onclick={handleModalConfirm}
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
  </span>
</AboutPage>
