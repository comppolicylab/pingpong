<script lang="ts">
  import { Button, Heading } from 'flowbite-svelte';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { page } from '$app/stores';
  import SanitizeFlowbite from '$lib/components/SanitizeFlowbite.svelte';
  import { loading } from '$lib/stores/general.js';

  export let data;

  $: agreement = data.agreement;

  const logout = async () => {
    await goto('/logout');
  };

  const goToDestination = async () => {
    $loading = true;
    const destination = $page.url.searchParams.get('destination') || '/';
    await goto(destination);
    $loading = false;
  };

  const acceptAgreement = async () => {
    if (!agreement) {
      return;
    }
    $loading = true;
    const response = await api.acceptUserAgreement(fetch, agreement.id).then(api.expandResponse);
    if (response.error) {
      $loading = false;
      return sadToast(response.error.detail || 'Unknown error accepting agreement');
    }
    happyToast('Agreement accepted.');
    await goToDestination();
    $loading = false;
  };
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-7/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-8 bg-white">
      <div class="flex flex-col gap-4">
        {#if agreement !== null}
          <SanitizeFlowbite html={agreement?.code} />
          <div class="flex-row gap-4 text-center flex justify-end mt-4">
            <Button
              class="text-blue-dark-40 bg-white border border-blue-dark-40 rounded-full hover:bg-blue-dark-40 hover:text-white"
              type="button"
              on:click={logout}
              disabled={$loading}>Exit PingPong</Button
            >
            <Button
              type="submit"
              class="text-white bg-orange rounded-full hover:bg-orange-dark"
              on:click={acceptAgreement}
              disabled={$loading}>Accept</Button
            >
          </div>
        {:else}
          <p class="text-lg text-gray-800">No agreement found.</p>
          <div class="flex-row gap-4 text-center flex justify-end mt-4">
            <Button
              class="text-blue-dark-40 bg-white border border-blue-dark-40 rounded-full hover:bg-blue-dark-40 hover:text-white w-fit items"
              type="button"
              on:click={goToDestination}
              disabled={$loading}>Continue to PingPong</Button
            >
          </div>
        {/if}
      </div>
    </div>
  </div>
</div>
