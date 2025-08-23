<script lang="ts">
	import Button from '../ui/button/button.svelte';

	let { classId }: { classId: string } = $props();
</script>

<Button variant="outline" size="sm" class="whitespace-nowrap" href={`/preassessment/${classId}`}>
	See student list
</Button>
