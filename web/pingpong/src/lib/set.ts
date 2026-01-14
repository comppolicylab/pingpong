/**
 * Test if two sets contain the same elements.
 */
export const setsEqual = (set1: Set<unknown>, set2: Set<unknown>): boolean => {
	if (set1.size !== set2.size) {
		return false;
	}

	for (const item of set1) {
		if (!set2.has(item)) {
			return false;
		}
	}

	return true;
};
