<script lang="ts">
  import type { SubmitFunction } from '@sveltejs/kit';
  import { enhance } from '$app/forms';
  import Logo from '$lib/components/Logo.svelte';
  import {
    P,
    A,
    InputAddon,
    Input,
    Helper,
    GradientButton,
    Button,
    Heading,
    ButtonGroup
  } from 'flowbite-svelte';
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

<div class="h-screen v-screen flex items-center justify-center bg-sky-800">
  <div class="flex items-center justify-center flex-col">
    <div><Logo size={20} extraClass="fill-amber-600" /></div>
    <div class="mt-4">
      <Heading tag="h1" class="text-amber-500 logo">PingPong</Heading>
    </div>
    <div class="mt-8 w-90">
      {#if form?.success}
        <div class="text-green-300">
          Success! Follow the link in your email to finish signing in.
        </div>
      {:else}
        <form action="/login?/loginWithMagicLink" method="POST" use:enhance={login}>
          <ButtonGroup class="w-full">
            <InputAddon>
              <EnvelopeSolid />
            </InputAddon>
            <Input
              value={form?.email ?? ''}
              readonly={loggingIn || null}
              type="email"
              placeholder="you@school.edu"
              name="email"
              id="email"
            ></Input>
            <GradientButton type="submit" color="cyanToBlue" disabled={loggingIn}
              >Login</GradientButton
            >
          </ButtonGroup>
          {#if form?.error}
            <div class="p-2">
              <P class="text-red-500">We could not sign you in.</P>
              <P class="text-red-500"
                >Please make sure you are using the correct email address and try again.
              </P>
            </div>
          {:else}
            <Helper class="my-2 text-white text-sm">Log in with your school email address.</Helper>
          {/if}
        </form>
      {/if}
    </div>
  </div>
</div>
