<script lang="ts">
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { Button, InputAddon, Input, Heading, ButtonGroup } from 'flowbite-svelte';
  import { EnvelopeSolid } from 'flowbite-svelte-icons';
  import { writable } from 'svelte/store';
  import { sadToast } from '$lib/toast';
  import * as api from '$lib/api';
  import { page } from '$app/stores';

  export let form;
  const forward = $page.url.searchParams.get('forward') || '/';
  const expired = $page.url.searchParams.get('expired') === 'true' || false;
  const new_link = $page.url.searchParams.get('new_link') === 'true' || false;
  const loggingIn = writable(false);
  const success = writable(false);

  $: email = form?.email ?? '';

  const loginWithMagicLink = async (evt: SubmitEvent) => {
    evt.preventDefault();
    loggingIn.set(true);

    const form = evt.target as HTMLFormElement;
    const formData = new FormData(form);
    const d = Object.fromEntries(formData.entries());

    const email = d.email?.toString();
    if (!email) {
      loggingIn.set(false);
      sadToast('Please provide a valid email address');
      return;
    }

    const result = await api.loginWithMagicLink(fetch, email, forward);
    if (result.$status < 300) {
      success.set(true);
      loggingIn.set(false);
    } else {
      sadToast(result.detail?.toString() || 'Could not log in');
      loggingIn.set(false);
    }
  };
</script>

<div class="h-[calc(100dvh-3rem)] v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 lg:w-6/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-5 md:px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-5 md:px-12 pb-16 pt-10 bg-white">
      {#if $success}
        <div class="text-4xl text-center font-serif font-bold mt-5 mb-2 text-blue-dark-50">
          Success!
        </div>
        <div class="text-lg text-center">Follow the link in your email to finish signing in.</div>
      {:else if new_link}
        <div class="text-4xl text-center font-serif font-bold mt-5 mb-4 text-blue-dark-50">
          Let's try this again.
        </div>
        <div class="text-lg text-center">
          This log-in link isn't currently valid.<br />We sent a new link to your email.
        </div>
      {:else}
        <div class="mb-6">
          {#if expired}
            <div class="text-4xl text-center font-serif font-bold mb-2 text-blue-dark-50">
              Let's try this again.
            </div>
            <div class="text-lg text-center">
              This log-in link isn't currently valid.<br />Try logging in with your school email
              address again.
            </div>
          {:else}
            <div class="text-4xl text-center font-serif font-bold mb-2 text-blue-dark-50">
              {form?.error ? 'We could not sign you in.' : 'Welcome to PingPong'}
            </div>
            <div class="text-lg text-center">
              {form?.error
                ? 'Please make sure you are using the correct email address and try again.'
                : 'Use your school email address to log in.'}
            </div>
          {/if}
        </div>
        <form on:submit={loginWithMagicLink}>
          <ButtonGroup class="w-full rounded-full bg-blue-light-50 shadow-inner p-4">
            <InputAddon class="rounded-none border-none bg-transparent text-blue-dark-30">
              <EnvelopeSolid />
            </InputAddon>
            <Input
              bind:value={email}
              readonly={$loggingIn || null}
              type="email"
              placeholder="you@school.edu"
              name="email"
              id="email"
              class="bg-transparent border-none text-md"
            ></Input>
            <Button
              pill
              class="p-3 px-6 mr-2 rounded-full bg-orange-dark hover:bg-orange text-white text-md py-2 px-4"
              type="submit"
              disabled={$loggingIn || !email}>Login</Button
            >
          </ButtonGroup>
        </form>
      {/if}
    </div>
  </div>
</div>
