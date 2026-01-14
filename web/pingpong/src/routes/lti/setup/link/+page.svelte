<script lang="ts">
  import { Button, Heading, Radio } from 'flowbite-svelte';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { ArrowLeftOutline, InfoCircleSolid } from 'flowbite-svelte-icons';
  import * as api from '$lib/api';
  import { loading } from '$lib/stores/general.js';
  import { resolve } from '$app/paths';

  export let data;

  const { context, groups, ltiClassId } = data;

  // Build display name for the course
  const courseName =
    context.course_code && context.course_name
      ? `${context.course_code}: ${context.course_name}`
      : context.course_name || context.course_code || 'Your Course';

  let selectedGroupId: number | undefined = undefined;
  let error = '';

  const goBack = () => {
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    goto(`/lti/setup?lti_class_id=${ltiClassId}`);
  };

  const handleSubmit = async () => {
    if (!selectedGroupId) {
      error = 'Please select a group to link';
      return;
    }

    error = '';
    $loading = true;

    try {
      const result = await api
        .linkLTIGroup(fetch, ltiClassId, {
          class_id: selectedGroupId
        })
        .then(api.explodeResponse);

      // Redirect to the group's assistant page
      await goto(resolve(`/group/${result.class_id}/assistant`));
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to link group';
    } finally {
      $loading = false;
    }
  };
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-7/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-8 bg-white">
      <div class="flex flex-col gap-6">
        <div class="flex items-center gap-4">
          <button
            type="button"
            class="p-2 rounded-full hover:bg-gray-100 transition-colors"
            onclick={goBack}
          >
            <ArrowLeftOutline class="w-5 h-5" />
          </button>
          <div class="font-medium text-2xl">Link Existing Group</div>
        </div>

        <div class="text-gray-600">
          Link <span class="font-semibold">{courseName}</span> to one of your existing PingPong groups.
        </div>

        {#if groups.length === 0}
          <div class="flex flex-col items-center gap-4 py-8 text-center">
            <InfoCircleSolid class="w-12 h-12 text-gray-400" />
            <div class="text-gray-600">
              <p class="font-medium mb-2">No groups available to link</p>
              <p class="text-sm">
                You don't have any groups that can be linked to this course. Please create a new
                group instead.
              </p>
            </div>
            <!-- eslint-disable svelte/no-navigation-without-resolve -->
            <Button
              type="button"
              class="text-white bg-orange rounded-full hover:bg-orange-dark mt-4"
              onclick={() => goto(`/lti/setup/create?lti_class_id=${ltiClassId}`)}
            >
              Create New Group
            </Button>
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          </div>
        {:else}
          <form onsubmit={handleSubmit} class="flex flex-col gap-4">
            <div class="flex flex-col gap-2 max-h-64 overflow-y-scroll">
              {#each groups as group (group.id)}
                <label
                  for="group-{group.id}"
                  class="flex items-center p-4 border rounded-xl cursor-pointer hover:bg-gray-50 transition-colors {selectedGroupId ===
                  group.id
                    ? 'border-orange bg-orange-light'
                    : 'border-gray-200'}"
                >
                  <Radio
                    id="group-{group.id}"
                    name="group"
                    value={group.id}
                    bind:group={selectedGroupId}
                    class="mr-4"
                  />
                  <div class="flex-1">
                    <div class="font-medium">{group.name}</div>
                    <div class="text-sm text-gray-500">
                      {group.term}
                      {#if group.institution_name}
                        &bull; {group.institution_name}
                      {/if}
                    </div>
                  </div>
                </label>
              {/each}
            </div>

            <div
              class="text-sm text-gray-500 flex items-start gap-2 bg-blue-light-40 p-3 rounded-lg"
            >
              <InfoCircleSolid class="w-4 h-4 mt-0.5 shrink-0" />
              <span>A PingPong group can be linked to multiple Canvas courses.</span>
            </div>

            {#if error}
              <p class="text-red-500 text-sm">{error}</p>
            {/if}

            <div class="flex justify-end gap-4 mt-4">
              <Button
                type="button"
                color="alternative"
                class="rounded-full"
                onclick={goBack}
                disabled={$loading}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                class="text-white bg-orange rounded-full hover:bg-orange-dark"
                disabled={$loading || !selectedGroupId}
              >
                {$loading ? 'Linking...' : 'Link Group'}
              </Button>
            </div>
          </form>
        {/if}
      </div>
    </div>
  </div>
</div>
