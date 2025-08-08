<script lang="ts">
	import { Badge, type BadgeVariant } from '$lib/components/ui/badge/index.js';

	let { status }: { status: string } = $props();

	function toVariant(value: string): BadgeVariant {
		switch (value) {
			case 'accepted':
				return 'default';
			case 'in_review':
				return 'secondary';
			case 'rejected':
				return 'destructive';
			default:
				return 'outline';
		}
	}

	function humanize(value: string): string {
		return value
			.split('_')
			.map((p) => (p ? p[0].toUpperCase() + p.slice(1) : p))
			.join(' ');
	}
</script>

<Badge variant={toVariant(status)}>
	{humanize(status)}
</Badge>
