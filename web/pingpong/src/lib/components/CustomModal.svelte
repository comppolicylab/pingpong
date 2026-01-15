<script lang="ts">
	import { Button, CloseButton, Heading, Textarea } from 'flowbite-svelte';
	import { createEventDispatcher } from 'svelte';
	import SanitizeFlowbite from './SanitizeFlowbite.svelte';
	import PingPongLogo from './PingPongLogo.svelte';
	import { loading } from '$lib/stores/general';

	interface Props {
		// Props
		open?: boolean;
		code?: string;
		preventEdits?: boolean;
	}

	let { open = $bindable(false), code = $bindable(''), preventEdits = false }: Props = $props();

	// Event dispatcher
	const dispatch = createEventDispatcher();

	// Handle closing modal
	function closeModal() {
		dispatch('close');
	}

	// Handle click outside
	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (target.classList.contains('modal-backdrop')) {
			closeModal();
		}
	}

	// Handle escape key
	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			closeModal();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<!-- Backdrop -->
	<div class="fixed inset-0 z-40 bg-gray-900/50" aria-hidden="true"></div>

	<!-- Modal -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center overflow-auto"
		role="dialog"
		aria-modal="true"
	>
		<!-- Clickable overlay -->
		<button
			type="button"
			class="modal-backdrop absolute inset-0 h-full w-full cursor-default"
			aria-label="Close modal"
			onclick={handleClickOutside}
		></button>

		<!-- Modal content -->
		<div class="relative m-4 flex h-4/5 w-4/5 flex-col rounded-lg bg-white shadow">
			<div class="flex flex-row items-center justify-between p-4">
				<Heading tag="h3" class="ml-2 w-full text-2xl font-semibold">User Agreement Preview</Heading
				>
				<CloseButton onclick={closeModal} label="Close modal" />
			</div>

			<div class="flex h-full w-full flex-row gap-0">
				<div class="flex w-1/3 flex-col bg-gray-100 p-4">
					<Textarea
						id="code"
						rows={10}
						class="h-full w-full font-mono"
						bind:value={code}
						disabled={$loading || preventEdits}
						placeholder="Enter your HTML code here..."
					/>
				</div>
				<div class="h-full w-2/3 grow overflow-y-auto">
					<div class="flex h-fit min-h-full w-full flex-col bg-blue-dark-50 py-10">
						<div class="flex items-center justify-center">
							<div class="flex w-11/12 max-w-2xl flex-col overflow-hidden rounded-4xl lg:w-7/12">
								<header class="bg-blue-dark-40 px-12 py-8">
									<Heading tag="h4" class="logo w-full text-center"
										><PingPongLogo size="full" /></Heading
									>
								</header>
								<div class="bg-white px-12 py-8">
									<div class="flex flex-col gap-4">
										<SanitizeFlowbite html={code} />
										<div class="mt-4 flex flex-row justify-end gap-4 text-center">
											<Button
												class="rounded-full border border-blue-dark-40 bg-white text-blue-dark-40 hover:bg-blue-dark-40 hover:text-white"
												type="button">Exit PingPong</Button
											>
											<Button class="rounded-full bg-orange text-white hover:bg-orange-dark"
												>Accept</Button
											>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
{/if}
