export type EmailTuple = [string | null, string, boolean];

export function parseAddresses(input: string): EmailTuple[] {
  const result: EmailTuple[] = [];

  // Split the input string by newlines
  const lines = input
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);

  for (const line of lines) {
    // Check if the line contains a group definition (e.g., Friends: alice@example.com, bob@example.com;)
    const groupMatch = line.match(/^(.*?):\s*(.*?)\s*;$/);

    if (groupMatch) {
      // Parse the group: groupName and groupAddresses
      const [, , groupAddresses] = groupMatch;
      const innerAddresses = groupAddresses.split(/,\s*/).map((addr) => addr.trim());

      // Push each address in the group, skipping the group name
      for (const addr of innerAddresses) {
        result.push(...parseSingleAddress(addr));
      }
      continue;
    }

    // Split the line by commas in case it contains multiple addresses (e.g., john@example.com, jane@example.com)
    const addresses = line.split(/,\s*/).map((addr) => addr.trim());

    // Process each address in the line
    for (const address of addresses) {
      result.push(...parseSingleAddress(address));
    }
  }

  return result;
}

// Helper function to check if an email address is valid
function isEmailValid(email: string): boolean {
  const emailRegex =
    /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/; // Basic email regex pattern
  return emailRegex.test(email);
}

// Helper function to parse a single address or name <email>
function parseSingleAddress(address: string): EmailTuple[] {
  const match = address.match(/^(.*?)\s*<([^>]+)>$/);

  if (match) {
    // If there's a match, we have a name and an email
    const [, name, email] = match;
    const isValid = isEmailValid(email.trim());
    return [[name.trim() || null, email.trim(), isValid]];
  } else {
    // If it's just an email address, check validity
    const isValid = isEmailValid(address.trim());
    return [[null, address.trim(), isValid]];
  }
}
