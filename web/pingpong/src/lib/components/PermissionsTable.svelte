<script lang="ts">
	import {
		Table,
		TableHead,
		TableHeadCell,
		TableBody,
		TableBodyRow,
		TableBodyCell
	} from 'flowbite-svelte';
	import { CheckOutline, CloseOutline } from 'flowbite-svelte-icons';

	interface Props {
		permissions?: { name: string; member: boolean; moderator: boolean }[];
	}

	let { permissions = [] }: Props = $props();

	function getStatusClass(status: boolean) {
		return status ? 'text-blue-dark-30' : 'text-orange-dark opacity-80';
	}
</script>

<div class="overflow-x-auto">
	<Table class="w-full">
		<TableHead>
			<TableHeadCell class="bg-gray-100 py-2">Permissions</TableHeadCell>
			<TableHeadCell class="bg-gray-100 py-2 text-center">Members</TableHeadCell>
			<TableHeadCell class="bg-gray-100 py-2 text-center">Moderators</TableHeadCell>
		</TableHead>
		<TableBody>
			{#each permissions as { name, member, moderator } (name)}
				<TableBodyRow>
					<TableBodyCell class="py-1 font-normal whitespace-normal">{name}</TableBodyCell>
					{#each [member, moderator] as status, idx (idx)}
						<TableBodyCell class="py-1 text-center">
							<span
								class={`inline-flex h-5 w-5 items-center justify-center ${getStatusClass(status)}`}
							>
								{#if status}
									<CheckOutline class="h-4 w-4" strokeWidth="3" />
								{:else}
									<CloseOutline class="h-4 w-4" strokeWidth="3" />
								{/if}
							</span>
						</TableBodyCell>
					{/each}
				</TableBodyRow>
			{/each}
		</TableBody>
	</Table>
</div>
