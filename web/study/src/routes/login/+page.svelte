<script lang="ts">
	import LoginForm from '$lib/components/login-form.svelte';
	import Building2 from '@lucide/svelte/icons/building-2';
</script>

<div class="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted p-6 md:p-10">
	<div class="flex w-full max-w-sm flex-col gap-6">
		<a
			href="https://pingpong.hks.harvard.edu/eduaccess"
			class="flex items-center gap-2 self-center font-medium"
		>
			<div
				class="flex size-6 items-center justify-center rounded-md bg-primary text-primary-foreground"
			>
				<Building2 class="size-4" />
			</div>
			PingPong College Study
		</a>
		<LoginForm />
	</div>
</div>
