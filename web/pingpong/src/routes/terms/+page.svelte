<script lang="ts">
  import { Button, Heading, List, Li } from 'flowbite-svelte';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { goto } from '$app/navigation';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { page } from '$app/stores';

  export let data;

  let loading = false;

  const acceptTerms = async () => {
    loading = true;
    const result = await api.acceptTerms(fetch);
    const response = api.expandResponse(result);
    if (response.error) {
      sadToast(response.error.detail || 'An unknown error occurred');
    } else {
      happyToast(`Terms accepted successfully.`);
      const destination = $page.url.searchParams.get('forward') || '/';
      await goto(destination);
    }
    loading = false;
  };

  const logout = async () => {
    await goto('/logout');
  };

</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-7/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-8 bg-white">
      <div class="flex flex-col gap-4">
        {@html terms}
        <div class="flex-row gap-4 text-center flex justify-end mt-4">
          <Button
            class="text-blue-dark-40 bg-white border border-blue-dark-40 rounded-full hover:bg-blue-dark-40 hover:text-white"
            type="button"
            on:click={logout}
            disabled={loading}>Exit PingPong</Button
          >
          <Button
            type="submit"
            class="text-white bg-orange rounded-full hover:bg-orange-dark"
            disabled={loading}>Accept</Button
          >
        </div>
      </div>
    </div>
  </div>
</div>
