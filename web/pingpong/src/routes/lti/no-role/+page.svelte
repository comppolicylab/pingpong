<script lang="ts">
  import { Button } from 'flowbite-svelte';
  import { InfoCircleSolid } from 'flowbite-svelte-icons';
  import AboutPage from '$lib/components/AboutPage.svelte';
</script>

<AboutPage nonAuthed={true} linksOpenInNewTab={true}>
  <div class="px-12 pt-8" slot="header">
    <div class="w-full rounded-lg border border-gray-300 bg-gray-100 p-6">
      <div class="flex items-start gap-4">
        <InfoCircleSolid class="w-6 h-6 text-gray-500 shrink-0 mt-0.5" />
        <div class="flex-1">
          <h5 class="text-lg font-medium text-gray-900 mb-2">
            You don't have a compatible role to access PingPong
          </h5>
          <p class="text-sm text-gray-600 mb-4">
            PingPong only supports teacher and student roles. If you believe this is an error or
            need assistance, please contact your Canvas administrator.
          </p>
          <div class="border-t border-gray-200 pt-4 mt-2">
            <p class="text-sm text-gray-600 mb-3">
              Already have a PingPong account? You can access it directly in the meantime.
            </p>
            <Button
              pill
              class="bg-orange-dark text-white hover:bg-orange"
              href="/login"
              target="_blank"
            >
              Log in to PingPong
            </Button>
          </div>
        </div>
      </div>
    </div>
  </div>
</AboutPage>
