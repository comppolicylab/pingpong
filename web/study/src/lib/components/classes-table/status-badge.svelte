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
			case 'withdrawn':
				return 'secondary';
			default:
				return 'secondary';
		}
	}

	function toLabel(value: string): string {
		switch (value) {
			case 'accepted':
				return 'Accepted';
			case 'in_review':
				return 'In Review';
			case 'rejected':
				return 'Not Selected';
			case 'withdrawn':
				return 'Withdrawn';
			default:
				return 'In Review';
		}
	}
</script>

<Badge variant={toVariant(status)}>
	{toLabel(status)}
</Badge>
