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

  export let permissions: { name: string; member: boolean; moderator: boolean }[] = [];

  function getStatusClass(status: boolean) {
    return status ? 'text-blue-dark-30' : 'text-orange-dark opacity-80';
  }
</script>

<div class="overflow-x-auto">
  <Table class="w-full">
    <TableHead>
      <TableHeadCell class="bg-gray-100 py-2">Permissions</TableHeadCell>
      <TableHeadCell class="bg-gray-100 text-center py-2">Members</TableHeadCell>
      <TableHeadCell class="bg-gray-100 text-center py-2">Moderators</TableHeadCell>
    </TableHead>
    <TableBody>
      {#each permissions as { name, member, moderator } (name)}
        <TableBodyRow>
          <TableBodyCell class="py-1 font-normal whitespace-normal">{name}</TableBodyCell>
          {#each [member, moderator] as status, idx (idx)}
            <TableBodyCell class="text-center py-1">
              <span
                class={`inline-flex items-center justify-center w-5 h-5 ${getStatusClass(status)}`}
              >
                {#if status}
                  <CheckOutline class="w-4 h-4" strokeWidth="3" />
                {:else}
                  <CloseOutline class="w-4 h-4" strokeWidth="3" />
                {/if}
              </span>
            </TableBodyCell>
          {/each}
        </TableBodyRow>
      {/each}
    </TableBody>
  </Table>
</div>
