/**
 * Format a size in bytes to a human readable string.
 */
export const humanSize = (size: number, precision: number = 0): string => {
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];

  let unit = 0;
  while (size >= 1024) {
    size /= 1024;
    unit++;
  }

  return size.toFixed(precision) + ' ' + units[unit];
}
