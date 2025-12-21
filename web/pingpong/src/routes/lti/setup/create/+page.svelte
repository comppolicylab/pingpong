<script lang="ts">
  import { Button, Heading, Label, Input, Select } from 'flowbite-svelte';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { ArrowLeftOutline } from 'flowbite-svelte-icons';
  import * as api from '$lib/api';
  import { loading } from '$lib/stores/general.js';

  export let data;

  const { context, ltiClassId } = data;

  // Pre-fill form with LTI context data
  // Name: "Course Code: Course Name"
  let name =
    context.course_code && context.course_name
      ? `${context.course_code}: ${context.course_name}`
      : context.course_name || context.course_code || '';

  let term = context.course_term || '';
  let institutionId: number | null =
    context.institutions.length === 1 ? context.institutions[0].id : null;

  let error = '';

  const goBack = () => {
    goto(`/lti/setup?lti_class_id=${ltiClassId}`);
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      error = 'Please enter a group name';
      return;
    }
    if (!term.trim()) {
      error = 'Please enter a session/term';
      return;
    }
    if (!institutionId) {
      error = 'Please select an institution';
      return;
    }

    error = '';
    $loading = true;

    try {
      const result = await api
        .createLTIGroup(fetch, ltiClassId, {
          name: name.trim(),
          term: term.trim(),
          institution_id: institutionId
        })
        .then(api.explodeResponse);

      // Redirect to the new group's assistant page
      await goto(`/group/${result.class_id}/assistant`);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to create group';
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
            on:click={goBack}
          >
            <ArrowLeftOutline class="w-5 h-5" />
          </button>
          <div class="font-medium text-2xl">Create New Group</div>
        </div>

        <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4">
          <div>
            <Label for="name" class="mb-2">Group Name</Label>
            <Input
              id="name"
              bind:value={name}
              placeholder="e.g., CS101: Introduction to Programming"
              required
            />
          </div>

          <div>
            <Label for="term" class="mb-2">Session / Term</Label>
            <Input id="term" bind:value={term} placeholder="e.g., Fall 2025" required />
          </div>

          <div>
            <Label for="institution" class="mb-2">Institution</Label>
            {#if context.institutions.length === 0}
              <p class="text-red-500 text-sm">
                No institutions with billing are available. Please contact your administrator.
              </p>
            {:else if context.institutions.length === 1}
              <Input id="institution" value={context.institutions[0].name} disabled />
            {:else}
              <Select id="institution" bind:value={institutionId} required>
                <option value={null}>Select an institution</option>
                {#each context.institutions as inst}
                  <option value={inst.id}>{inst.name}</option>
                {/each}
              </Select>
            {/if}
          </div>

          {#if error}
            <p class="text-red-500 text-sm">{error}</p>
          {/if}

          <div class="flex justify-end gap-4 mt-4">
            <Button
              type="button"
              color="alternative"
              class="rounded-full"
              on:click={goBack}
              disabled={$loading}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              class="text-white bg-orange rounded-full hover:bg-orange-dark"
              disabled={$loading || context.institutions.length === 0}
            >
              {$loading ? 'Creating...' : 'Create Group'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>
