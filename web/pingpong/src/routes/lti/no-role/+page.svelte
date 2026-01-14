<script lang="ts">
	import { Button } from 'flowbite-svelte';
	import { InfoCircleSolid } from 'flowbite-svelte-icons';
	import AboutPage from '$lib/components/AboutPage.svelte';
</script>

<AboutPage nonAuthed={true} linksOpenInNewTab={true}>
	<div class="px-12 pt-8" slot="header">
		<div class="w-full rounded-lg border border-gray-300 bg-gray-100 p-6">
			<div class="flex items-start gap-4">
				<InfoCircleSolid class="mt-0.5 h-6 w-6 shrink-0 text-gray-500" />
				<div class="flex-1">
					<h5 class="mb-2 text-lg font-medium text-gray-900">
						You don't have a compatible role to access PingPong
					</h5>
					<p class="mb-4 text-sm text-gray-600">
						PingPong only supports teacher and student roles. If you believe this is an error or
						need assistance, please contact your Canvas administrator.
					</p>
					<div class="mt-2 border-t border-gray-200 pt-4">
						<p class="mb-3 text-sm text-gray-600">
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
