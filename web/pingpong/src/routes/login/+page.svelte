<script lang="ts">
  import {enhance} from "$app/forms";
  import Logo from '$lib/components/Logo.svelte';
  import {P, A, InputAddon, Input, Label, GradientButton, Button, Heading, ButtonGroup} from 'flowbite-svelte';
  import {EnvelopeSolid} from 'flowbite-svelte-icons';

  export let form;

  let loggingIn = false;

  const login = () => {
    loggingIn = true;
    return async ({update}) => {
      loggingIn = false;
      return update();
    }
  }
</script>

<div class="h-screen v-screen flex items-center justify-center bg-sky-800">
  <div class="flex items-center justify-center flex-col">
    <div><Logo size="20" extraClass="fill-amber-600" /></div>
    <div class="mt-4">
      <Heading tag="h1" class="text-amber-500">PingPong</Heading>
    </div>
    <div class="mt-8 w-90">
      {#if form?.success}
        <div class="text-green-300">Success! Follow the link in your email to finish signing in.</div>
      {:else}
        <form action="/login?/loginWithMagicLink" method="POST" use:enhance={login}>
          <Label for="email" class="mb-2 text-white">Log in with your school email address:</Label>
            <ButtonGroup class="w-full">
              <InputAddon>
              <EnvelopeSolid />
              </InputAddon>
              <Input value={form?.email ?? ''} readonly={loggingIn || null} type="email" placeholder="you@school.edu" name="email" id="email"></Input>
                <GradientButton type="submit" color="cyanToBlue" disabled={loggingIn}>Login</GradientButton>
            </ButtonGroup>
          {#if form?.error}
            <div class="text-red-500 p-2">
              <P>
                We could not sign you in.
              </P>
              <P>Please make sure you are using the correct email address and try again.
              </P>
            </div>
          {/if}
          </form>
      {/if}
    </div>
  </div>
</div>
