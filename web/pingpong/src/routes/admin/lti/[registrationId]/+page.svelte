<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import {
    Button,
    Heading,
    Helper,
    Input,
    Label,
    Textarea,
    Toggle,
    Badge,
    Card,
    MultiSelect
  } from 'flowbite-svelte';
  import { ArrowRightOutline, CheckCircleSolid, CloseCircleSolid } from 'flowbite-svelte-icons';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import * as api from '$lib/api';
  import { happyToast, sadToast } from '$lib/toast';
  import { loading } from '$lib/stores/general.js';
  import { resolve } from '$app/paths';

  export let data;

  let registration: api.LTIRegistrationDetail = data.registration;
  let availableInstitutions: api.Institution[] = data.availableInstitutions;

  // Editable fields
  let draftFriendlyName = registration.friendly_name || '';
  let draftAdminName = registration.admin_name || '';
  let draftAdminEmail = registration.admin_email || '';
  let draftInternalNotes = registration.internal_notes || '';
  let draftReviewNotes = registration.review_notes || '';
  let selectedInstitutionIds: number[] = registration.institutions.map((i) => i.id);

  // Loading states
  let saving = false;
  let settingStatus = false;
  let togglingEnabled = false;
  let savingInstitutions = false;

  $: institutionOptions = availableInstitutions.map((inst) => ({
    value: inst.id,
    name: inst.name
  }));

  const getStatusBadge = (status: api.LTIRegistrationReviewStatus) => {
    switch (status) {
      case 'approved':
        return { color: 'green' as const, text: 'Approved' };
      case 'rejected':
        return { color: 'red' as const, text: 'Rejected' };
      case 'pending':
      default:
        return { color: 'yellow' as const, text: 'Pending Review' };
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'N/A';
    return new Date(dateStr).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const formatJson = (jsonStr: string | null): string => {
    if (!jsonStr) return 'No data available';
    try {
      const parsed = JSON.parse(jsonStr);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return jsonStr;
    }
  };

  const getReviewerName = (reviewer: api.LTIRegistrationReviewer | null) => {
    if (!reviewer) return 'Not yet reviewed';
    if (reviewer.display_name) return reviewer.display_name;
    if (reviewer.first_name && reviewer.last_name)
      return `${reviewer.first_name} ${reviewer.last_name}`;
    if (reviewer.first_name) return reviewer.first_name;
    return reviewer.email || 'Unknown';
  };

  const refresh = async () => {
    const [regResponse, instResponse] = await Promise.all([
      api.getLTIRegistration(fetch, registration.id).then(api.expandResponse),
      api.getInstitutionsWithDefaultAPIKey(fetch).then(api.expandResponse)
    ]);
    if (regResponse.error || !regResponse.data) {
      sadToast(regResponse.error?.detail || 'Unable to refresh registration');
      return;
    }
    if (instResponse.error || !instResponse.data) {
      sadToast(instResponse.error?.detail || 'Unable to refresh institutions');
      return;
    }
    registration = regResponse.data;
    availableInstitutions = instResponse.data.institutions;
    draftFriendlyName = registration.friendly_name || '';
    draftAdminName = registration.admin_name || '';
    draftAdminEmail = registration.admin_email || '';
    draftInternalNotes = registration.internal_notes || '';
    draftReviewNotes = registration.review_notes || '';
    selectedInstitutionIds = registration.institutions.map((i) => i.id);
  };

  const saveChanges = async () => {
    if ($loading || saving) return;
    saving = true;
    try {
      const response = api.expandResponse(
        await api.updateLTIRegistration(fetch, registration.id, {
          friendly_name: draftFriendlyName || null,
          admin_name: draftAdminName || null,
          admin_email: draftAdminEmail || null,
          internal_notes: draftInternalNotes || null,
          review_notes: draftReviewNotes || null
        })
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not save changes');
        return;
      }
      happyToast('Changes saved');
      await refresh();
      await invalidateAll();
    } catch (err) {
      console.error(err);
      sadToast('Could not save changes');
    } finally {
      saving = false;
    }
  };

  const saveInstitutions = async () => {
    if ($loading || savingInstitutions) return;
    savingInstitutions = true;
    try {
      const response = api.expandResponse(
        await api.setLTIRegistrationInstitutions(fetch, registration.id, {
          institution_ids: selectedInstitutionIds
        })
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not save institutions');
        return;
      }
      happyToast('Institutions updated');
      await refresh();
      await invalidateAll();
    } catch (err) {
      console.error(err);
      sadToast('Could not save institutions');
    } finally {
      savingInstitutions = false;
    }
  };

  const setStatus = async (status: api.LTIRegistrationReviewStatus) => {
    if ($loading || settingStatus) return;
    settingStatus = true;
    try {
      const response = api.expandResponse(
        await api.setLTIRegistrationStatus(fetch, registration.id, { review_status: status })
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not update status');
        return;
      }
      happyToast(`Registration ${status}`);
      await refresh();
      await invalidateAll();
    } catch (err) {
      console.error(err);
      sadToast('Could not update status');
    } finally {
      settingStatus = false;
    }
  };

  const toggleEnabled = async () => {
    if ($loading || togglingEnabled) return;
    togglingEnabled = true;
    const newEnabled = !registration.enabled;
    try {
      const response = api.expandResponse(
        await api.setLTIRegistrationEnabled(fetch, registration.id, { enabled: newEnabled })
      );
      if (response.error) {
        sadToast(response.error.detail || 'Could not update enabled status');
        return;
      }
      happyToast(newEnabled ? 'Integration enabled' : 'Integration disabled');
      await refresh();
    } catch (err) {
      console.error(err);
      sadToast('Could not update enabled status');
    } finally {
      togglingEnabled = false;
    }
  };

  $: statusBadge = getStatusBadge(registration.review_status);
  $: hasChanges =
    draftFriendlyName !== (registration.friendly_name || '') ||
    draftAdminName !== (registration.admin_name || '') ||
    draftAdminEmail !== (registration.admin_email || '') ||
    draftInternalNotes !== (registration.internal_notes || '') ||
    draftReviewNotes !== (registration.review_notes || '');

  $: currentInstitutionIds = registration.institutions.map((i) => i.id);
  $: hasInstitutionChanges =
    selectedInstitutionIds.length !== currentInstitutionIds.length ||
    selectedInstitutionIds.some((id) => !currentInstitutionIds.includes(id));
</script>

<div class="relative h-full w-full flex flex-col">
  <PageHeader>
    <div slot="left">
      <h2 class="text-3xl text-color-blue-dark-50 font-serif font-bold px-4 py-3">
        LTI Registration
      </h2>
    </div>
    <div slot="right">
      <a
        href={resolve('/admin/lti')}
        class="text-sm text-blue-dark-50 font-medium bg-white rounded-full p-2 px-4 hover:text-white hover:bg-blue-dark-40 transition-all flex items-center gap-2"
        >All Registrations <ArrowRightOutline size="md" class="text-orange" /></a
      >
    </div>
  </PageHeader>

  <div class="h-full w-full overflow-y-auto p-12 space-y-8">
    <div class="flex flex-row flex-wrap justify-between mb-4 items-center gap-y-4">
      <div class="flex items-center gap-4">
        <Heading
          tag="h2"
          class="text-3xl font-serif font-medium text-dark-blue-40 shrink-0 max-w-max"
        >
          {registration.friendly_name || registration.canvas_account_name || 'LTI Registration'}
        </Heading>
        <Badge color={statusBadge.color} class="text-sm">{statusBadge.text}</Badge>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-sm text-gray-600">Enabled:</span>
        <Toggle
          checked={registration.enabled}
          disabled={togglingEnabled || registration.review_status !== 'approved'}
          color="blue"
          onchange={toggleEnabled}
        />
        {#if registration.review_status !== 'approved'}
          <span class="text-xs text-gray-400">Must be approved first</span>
        {/if}
      </div>
    </div>

    <!-- Status Actions -->
    <Card class="max-w-3xl">
      <Heading tag="h4" class="text-lg font-medium text-gray-900 mb-4">Review Actions</Heading>
      <div class="flex flex-wrap gap-3">
        <Button
          color="green"
          disabled={settingStatus || registration.review_status === 'approved'}
          onclick={() => setStatus('approved')}
          class="flex items-center gap-2"
        >
          <CheckCircleSolid size="sm" />
          Approve
        </Button>
        <Button
          color="red"
          disabled={settingStatus || registration.review_status === 'rejected'}
          onclick={() => setStatus('rejected')}
          class="flex items-center gap-2"
        >
          <CloseCircleSolid size="sm" />
          Reject
        </Button>
        <Button
          color="light"
          disabled={settingStatus || registration.review_status === 'pending'}
          onclick={() => setStatus('pending')}
        >
          Reset to Pending
        </Button>
      </div>
      {#if registration.review_by}
        <p class="text-sm text-gray-500 mt-3">
          Last reviewed by: {getReviewerName(registration.review_by)}
        </p>
      {/if}
    </Card>

    <!-- Editable Fields -->
    <div class="space-y-6 max-w-3xl">
      <Heading tag="h3" class="text-xl font-serif font-medium text-dark-blue-40">
        Registration Details
      </Heading>

      <div>
        <Label for="friendly-name" class="mb-1">Friendly Name</Label>
        <Helper class="mb-2">A human-readable name for this integration.</Helper>
        <Input
          type="text"
          name="friendly-name"
          id="friendly-name"
          placeholder="e.g., Stanford Canvas"
          bind:value={draftFriendlyName}
          disabled={$loading || saving}
        />
      </div>

      <div>
        <Label for="admin-name" class="mb-1">Admin Contact Name</Label>
        <Input
          type="text"
          name="admin-name"
          id="admin-name"
          placeholder="Contact person name"
          bind:value={draftAdminName}
          disabled={$loading || saving}
        />
      </div>

      <div>
        <Label for="admin-email" class="mb-1">Admin Contact Email</Label>
        <Input
          type="email"
          name="admin-email"
          id="admin-email"
          placeholder="admin@university.edu"
          bind:value={draftAdminEmail}
          disabled={$loading || saving}
        />
      </div>

      <div>
        <Label for="internal-notes" class="mb-1">Internal Notes</Label>
        <Helper class="mb-2">Private notes visible only to admins.</Helper>
        <Textarea
          id="internal-notes"
          name="internal-notes"
          rows={4}
          placeholder="Internal notes about this integration..."
          bind:value={draftInternalNotes}
          disabled={$loading || saving}
        />
      </div>

      <div>
        <Label for="review-notes" class="mb-1">Review Notes</Label>
        <Helper class="mb-2">Notes about the review decision.</Helper>
        <Textarea
          id="review-notes"
          name="review-notes"
          rows={4}
          placeholder="Reason for approval/rejection..."
          bind:value={draftReviewNotes}
          disabled={$loading || saving}
        />
      </div>

      <div class="flex justify-end pt-4">
        <Button
          class="bg-orange text-white rounded-full hover:bg-orange-dark"
          disabled={saving || !hasChanges}
          onclick={saveChanges}
        >
          Save Changes
        </Button>
      </div>
    </div>

    <!-- Associated Institutions -->
    <div class="space-y-4 max-w-3xl">
      <Heading tag="h3" class="text-xl font-serif font-medium text-dark-blue-40">
        Associated Institutions
      </Heading>
      <Helper class="mb-2">
        Select institutions that can use this LTI integration. Only institutions with a default API
        key configured are available.
      </Helper>
      {#if institutionOptions.length === 0}
        <p class="text-sm text-gray-500">
          No institutions with default API keys available. Configure a default API key for an
          institution first.
        </p>
      {:else}
        <MultiSelect
          items={institutionOptions}
          bind:value={selectedInstitutionIds}
          placeholder="Select institutions..."
          disabled={$loading || savingInstitutions}
        />
        <div class="flex justify-end pt-2">
          <Button
            class="bg-orange text-white rounded-full hover:bg-orange-dark"
            disabled={savingInstitutions || !hasInstitutionChanges}
            onclick={saveInstitutions}
          >
            Save Institutions
          </Button>
        </div>
      {/if}
    </div>

    <!-- Technical Details (Read-only) -->
    <div class="space-y-4">
      <Heading tag="h3" class="text-xl font-serif font-medium text-dark-blue-40">
        Technical Information
      </Heading>

      <Card size="none">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <span class="font-medium text-gray-700">Issuer:</span>
            <p class="text-gray-600 break-all">{registration.issuer}</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">Client ID:</span>
            <p class="text-gray-600 break-all">{registration.client_id || 'N/A'}</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">LMS Platform:</span>
            <p class="text-gray-600">{registration.lms_platform || 'Unknown'}</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">Canvas Account:</span>
            <p class="text-gray-600">{registration.canvas_account_name || 'N/A'}</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">Token Algorithm:</span>
            <p class="text-gray-600">{registration.token_algorithm}</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">LTI Classes:</span>
            <p class="text-gray-600">{registration.lti_classes_count} classes linked</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">Created:</span>
            <p class="text-gray-600">{formatDate(registration.created)}</p>
          </div>
          <div>
            <span class="font-medium text-gray-700">Last Updated:</span>
            <p class="text-gray-600">{formatDate(registration.updated)}</p>
          </div>
        </div>
      </Card>

      <Card size="none">
        <Heading tag="h4" class="text-md font-medium text-gray-900 mb-3"
          >OpenID Configuration</Heading
        >
        <pre
          class="whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-xs text-gray-700 overflow-x-auto max-h-96 overflow-y-auto">{formatJson(
            registration.openid_configuration
          )}</pre>
      </Card>

      <Card size="none">
        <Heading tag="h4" class="text-md font-medium text-gray-900 mb-3">Registration Data</Heading>
        <pre
          class="whitespace-pre-wrap rounded-lg bg-gray-50 p-4 text-xs text-gray-700 overflow-x-auto max-h-96 overflow-y-auto">{formatJson(
            registration.registration_data
          )}</pre>
      </Card>
    </div>
  </div>
</div>
