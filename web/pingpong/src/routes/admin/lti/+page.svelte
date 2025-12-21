<script lang="ts">
  import {
    Button,
    Heading,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Toggle,
    Badge
  } from 'flowbite-svelte';
  import { ArrowRightOutline, PenSolid } from 'flowbite-svelte-icons';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import type { LTIRegistration } from '$lib/api';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';

  export let data;

  let registrations: LTIRegistration[] = data.registrations;
  let togglingEnabled: Record<number, boolean> = {};

  const getStatusBadge = (status: api.LTIRegistrationReviewStatus) => {
    switch (status) {
      case 'approved':
        return { color: 'green' as const, text: 'Approved' };
      case 'rejected':
        return { color: 'red' as const, text: 'Rejected' };
      case 'pending':
      default:
        return { color: 'yellow' as const, text: 'Pending' };
    }
  };

  const getDisplayName = (reg: LTIRegistration) => {
    if (reg.friendly_name) return reg.friendly_name;
    if (reg.canvas_account_name) return reg.canvas_account_name;
    return reg.issuer;
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const toggleEnabled = async (reg: LTIRegistration) => {
    togglingEnabled = { ...togglingEnabled, [reg.id]: true };
    const newEnabled = !reg.enabled;
    const response = api.expandResponse(
      await api.setLTIRegistrationEnabled(fetch, reg.id, { enabled: newEnabled })
    );
    togglingEnabled = { ...togglingEnabled, [reg.id]: false };

    if (response.error || !response.data) {
      sadToast(response.error?.detail || 'Failed to update registration');
      return;
    }

    registrations = registrations.map((r) =>
      r.id === reg.id ? { ...r, enabled: response.data!.enabled } : r
    );
    happyToast(newEnabled ? 'Integration enabled' : 'Integration disabled');
  };
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">
        LTI Registrations
      </h2>
    </div>
    <div slot="right">
      <a
        href={`/admin`}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-blue-dark-40 transition-all flex items-center gap-2"
        >Admin page <ArrowRightOutline size="md" class="text-orange" /></a
      >
    </div>
  </PageHeader>

  <div class="h-full w-full overflow-y-auto p-12">
    <div class="flex flex-row flex-wrap justify-between mb-6 items-center gap-y-4">
      <Heading
        tag="h2"
        class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max mr-5"
        >Manage LTI Integrations</Heading
      >
    </div>

    <div class="flex flex-col gap-4">
      <Table class="w-full">
        <TableHead class="bg-blue-light-40 p-1 text-blue-dark-50 tracking-wide rounded-2xl">
          <TableHeadCell>Name</TableHeadCell>
          <TableHeadCell>Status</TableHeadCell>
          <TableHeadCell>Admin Contact</TableHeadCell>
          <TableHeadCell>Created</TableHeadCell>
          <TableHeadCell>Enabled</TableHeadCell>
          <TableHeadCell></TableHeadCell>
        </TableHead>
        <TableBody>
          {#if registrations.length === 0}
            <TableBodyRow>
              <TableBodyCell colspan={6} class="text-sm text-gray-500 py-4">
                No LTI registrations found.
              </TableBodyCell>
            </TableBodyRow>
          {/if}

          {#each registrations as registration}
            {@const statusBadge = getStatusBadge(registration.review_status)}
            <TableBodyRow>
              <TableBodyCell class="py-2 font-medium whitespace-normal max-w-xs">
                <div class="flex flex-col">
                  <span class="font-medium">{getDisplayName(registration)}</span>
                  {#if registration.lms_platform}
                    <span class="text-xs text-gray-500 uppercase">{registration.lms_platform}</span>
                  {/if}
                </div>
              </TableBodyCell>
              <TableBodyCell class="py-2">
                <Badge color={statusBadge.color}>{statusBadge.text}</Badge>
              </TableBodyCell>
              <TableBodyCell class="py-2 whitespace-normal max-w-xs">
                <div class="flex flex-col text-sm">
                  {#if registration.admin_name}
                    <span>{registration.admin_name}</span>
                  {/if}
                  {#if registration.admin_email}
                    <span class="text-gray-500">{registration.admin_email}</span>
                  {/if}
                  {#if !registration.admin_name && !registration.admin_email}
                    <span class="text-gray-400">Not provided</span>
                  {/if}
                </div>
              </TableBodyCell>
              <TableBodyCell class="py-2 text-sm text-gray-600">
                {formatDate(registration.created)}
              </TableBodyCell>
              <TableBodyCell class="py-2">
                <Toggle
                  checked={registration.enabled}
                  disabled={!!togglingEnabled[registration.id] ||
                    registration.review_status !== 'approved'}
                  color="blue"
                  on:change={() => toggleEnabled(registration)}
                />
              </TableBodyCell>
              <TableBodyCell class="py-2 text-right">
                <Button
                  pill
                  size="sm"
                  class="text-xs border border-blue-dark-40 text-blue-dark-40 shrink-0 flex flex-row gap-1.5 items-center justify-center bg-white rounded-full p-1 px-3 hover:text-white hover:bg-blue-dark-40 transition-all w-fit"
                  href={`/admin/lti/${registration.id}`}
                >
                  <PenSolid size="sm" class="mr-1" />
                  Details
                </Button>
              </TableBodyCell>
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    </div>
  </div>
</div>
