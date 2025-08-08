<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import CircleHelp from '@lucide/svelte/icons/circle-help';
	let { status }: { status: string } = $props();

	function toExplainer(value: string): string | undefined {
		switch (value) {
			case 'control':
				return 'This class will not receive access to the PingPong platform for this semester.';
			case 'treatment':
				return 'You and your students in this class will receive access to the PingPong platform for this semester.';
		}
	}

	function humanize(value: string): string {
		return value
			.split('_')
			.map((p) => (p ? p[0].toUpperCase() + p.slice(1) : p))
			.join(' ');
	}
</script>

<div class="flex items-center gap-2">
	{humanize(status)}

	<Tooltip.Provider delayDuration={150}>
		<Tooltip.Root>
			<Tooltip.Trigger>
				<CircleHelp size="16" class="text-muted-foreground" />
			</Tooltip.Trigger>
			<Tooltip.Content side="top" sideOffset={2} class="max-w-xs break-words whitespace-normal">
				<span class="text-sm">{toExplainer(status)}</span>
			</Tooltip.Content>
		</Tooltip.Root>
	</Tooltip.Provider>
</div>
