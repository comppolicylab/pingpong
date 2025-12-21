<script lang="ts">
  import { Button, Heading } from 'flowbite-svelte';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { PlusOutline, LinkOutline } from 'flowbite-svelte-icons';

  export let data;

  const { context, ltiClassId } = data;

  // Build display name: "Course Code: Course Name" or just the name if no code
  const courseName =
    context.course_code && context.course_name
      ? `${context.course_code}: ${context.course_name}`
      : context.course_name || context.course_code || 'Your Course';

  const goToCreate = () => {
    goto(`/lti/setup/create?lti_class_id=${ltiClassId}`);
  };

  const goToLink = () => {
    goto(`/lti/setup/link?lti_class_id=${ltiClassId}`);
  };
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-8/12 max-w-3xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-8 bg-white">
      <div class="flex flex-col gap-6">
        <div class="w-full">
          <div class="font-medium text-3xl mb-2">Welcome to PingPong!</div>
          <div class="text-lg text-gray-600">
            Set up PingPong for <span class="font-semibold">{courseName}</span>
            {#if context.course_term}
              <span class="text-gray-500">({context.course_term})</span>
            {/if}
          </div>
        </div>

        <div class="w-full">
          <p class="text-md text-gray-700 mb-6">
            Choose how you'd like to connect this course to PingPong:
          </p>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- Create New Group Card -->
            <button
              type="button"
              class="flex flex-col p-6 border-2 border-gray-200 rounded-2xl hover:border-orange hover:bg-orange-light transition-colors text-left cursor-pointer"
              on:click={goToCreate}
            >
              <div class="flex items-center gap-3 mb-3">
                <div class="w-10 h-10 bg-orange rounded-full flex items-center justify-center">
                  <PlusOutline class="w-5 h-5 text-white" />
                </div>
                <span class="font-semibold text-lg">Create New Group</span>
              </div>
              <p class="text-gray-600 text-sm">
                Set up a fresh PingPong group for this course. Best for new courses.
              </p>
            </button>

            <!-- Link Existing Group Card -->
            <button
              type="button"
              class="flex flex-col p-6 border-2 border-gray-200 rounded-2xl hover:border-orange hover:bg-orange-light transition-colors text-left cursor-pointer"
              on:click={goToLink}
            >
              <div class="flex items-center gap-3 mb-3">
                <div
                  class="w-10 h-10 bg-blue-dark-40 rounded-full flex items-center justify-center"
                >
                  <LinkOutline class="w-5 h-5 text-white" />
                </div>
                <span class="font-semibold text-lg">Link Existing Group</span>
              </div>
              <p class="text-gray-600 text-sm">
                Connect this course to a PingPong group you already manage.
              </p>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
