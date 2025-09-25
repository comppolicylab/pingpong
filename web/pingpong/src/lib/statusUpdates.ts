import type { StatusComponentUpdate } from './api';

export const computeLatestIncidentTimestamps = (
  components: Partial<Record<string, StatusComponentUpdate[]>>
): Record<string, number> => {
  const latest: Record<string, number> = {};

  for (const updates of Object.values(components)) {
    if (!updates) {
      continue;
    }

    for (const update of updates) {
      if (!update.updatedAt) {
        continue;
      }

      const timestamp = Date.parse(update.updatedAt);
      if (Number.isNaN(timestamp)) {
        continue;
      }

      const existing = latest[update.incidentId];
      if (existing === undefined || timestamp > existing) {
        latest[update.incidentId] = timestamp;
      }
    }
  }

  return latest;
};

export const filterLatestIncidentUpdates = (
  updates: StatusComponentUpdate[] | undefined,
  latestTimestamps: Record<string, number>
): StatusComponentUpdate[] => {
  if (!updates) {
    return [];
  }

  return updates.filter((update) => {
    if (!update.updatedAt) {
      return false;
    }

    const currentTimestamp = Date.parse(update.updatedAt);
    if (Number.isNaN(currentTimestamp)) {
      return false;
    }

    const latestTimestamp = latestTimestamps[update.incidentId];
    if (latestTimestamp === undefined) {
      return true;
    }

    return currentTimestamp === latestTimestamp;
  });
};
