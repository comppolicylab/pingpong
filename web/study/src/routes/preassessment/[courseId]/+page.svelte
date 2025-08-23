<script lang="ts">
	import DataTable from '$lib/components/common-table/data-table.svelte';
	import { columns } from '$lib/components/preassessment-table/columns.js';

	let { data } = $props();
</script>

<div class="flex flex-col gap-4">
	<DataTable data={data.preAssessmentStudents} {columns} />
</div>
