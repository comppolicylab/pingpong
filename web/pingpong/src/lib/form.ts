/**
 * Find the form where the event originated and try to submit it.
 */
export const submitParentForm = (evt: Event) => {
	const target = evt.target as HTMLInputElement;
	target.form?.requestSubmit();
};
