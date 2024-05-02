<script lang="ts">
  import type { SubmitFunction } from '@sveltejs/kit';
  import { enhance } from '$app/forms';
  import PingPongLogo from '$lib/components/PingPongLogo.svelte';
  import { Button, P, InputAddon, Input, Helper, Heading, ButtonGroup } from 'flowbite-svelte';
  import { EnvelopeSolid } from 'flowbite-svelte-icons';

  export let form;

  let loggingIn = false;

  const login: SubmitFunction = (e) => {
    if (!e.formData.get('email') || loggingIn) {
      e.cancel();
      return;
    }

    loggingIn = true;
    return async ({ update }) => {
      loggingIn = false;
      return update();
    };
  };
</script>

<div class="h-screen v-screen flex items-center justify-center">
  <div class="flex flex-col w-11/12 sm:w-6/12 max-w-2xl rounded-4xl overflow-hidden">
    <header class="bg-blue-dark-40 px-12 py-8">
      <Heading tag="h1" class="logo w-full text-center"><PingPongLogo size="full" /></Heading>
    </header>
    <div class="px-12 py-16 bg-white">
      {#if form?.success}
        <div class="text-orange">Success! Follow the link in your email to finish signing in.</div>
      {:else}
        <form action="/login?/loginWithMagicLink" method="POST" use:enhance={login}>
          <ButtonGroup class="w-full rounded-full bg-blue-light-50 shadow-inner p-4">
            <InputAddon class="rounded-none border-none bg-transparent text-blue-light-40">
              <EnvelopeSolid />
            </InputAddon>
            <Input
              value={form?.email ?? ''}
              readonly={loggingIn || null}
              type="email"
              placeholder="you@school.edu"
              name="email"
              id="email"
              class="bg-transparent border-none"
            ></Input>
            <Button
              pill
              class="p-3 px-6 mr-2 rounded-full bg-orange text-white hover:bg-orange-dark"
              type="submit"
              disabled={loggingIn}>Login</Button
            >
          </ButtonGroup>
          {#if form?.error}
            <div class="p-2">
              <P class="text-orange">We could not sign you in.</P>
              <P class="text-orange"
                >Please make sure you are using the correct email address and try again.
              </P>
            </div>
          {:else}
            <Helper class="my-2 text-black text-sm">Log in with your school email address.</Helper>
          {/if}
        </form>
      {/if}
    </div>
  </div>
</div>
