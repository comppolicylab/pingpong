<script lang="ts">
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { Heading } from 'flowbite-svelte';
  import { LTISessionToken } from '$lib/stores/lti';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';

  // If we have an LTI session token as a URL parameter, set it in the store
  const forward = page.url.searchParams.get('forward') || '/';
  const ltiSessionToken = page.url.searchParams.get('lti_session_token') || null;

  onMount(async () => {
    if (ltiSessionToken) {
      LTISessionToken.set(ltiSessionToken);
    }
    // Redirect to the forward URL after setting the token
    if (browser) {
      await goto(forward);
    }
  });
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-6/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-5 md:px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-5 md:px-12 py-16 bg-white">
      <div class="text-4xl text-center font-serif font-bold mb-2 text-blue-dark-50">
        We're logging you in...
      </div>
      <div class="text-lg text-center">Please wait a moment.</div>
    </div>
  </div>
</div>
