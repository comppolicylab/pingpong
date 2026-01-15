<script lang="ts">
	import {
		Table,
		TableHead,
		TableHeadCell,
		TableBody,
		TableBodyRow,
		TableBodyCell
	} from 'flowbite-svelte';

	interface Props {
		moderators?: { name: string | null; email: string }[];
	}

	let { moderators = [] }: Props = $props();
</script>

<div class="overflow-x-auto">
	<Table class="w-full">
		<TableHead>
			<TableHeadCell class="bg-gray-100 py-2">Name</TableHeadCell>
			<TableHeadCell class="bg-gray-100 py-2">Email</TableHeadCell>
		</TableHead>
		<TableBody>
			{#each moderators as { name, email } (email)}
				<TableBodyRow>
					{#if name}
						<TableBodyCell class="py-1 font-medium whitespace-normal">{name}</TableBodyCell>
					{:else}
						<TableBodyCell class="py-1 font-normal whitespace-normal italic"
							>No recorded name</TableBodyCell
						>
					{/if}
					<TableBodyCell class="py-1 font-normal whitespace-normal">{email}</TableBodyCell>
				</TableBodyRow>
			{/each}
		</TableBody>
	</Table>
</div>
