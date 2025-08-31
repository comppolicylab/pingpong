/**
 * Overall status of the session.
 */
export type SessionStatus = 'valid' | 'invalid' | 'missing' | 'error';

/**
 * Token information.
 */
export type SessionToken = {
	sub: string;
	exp: number;
	iat: number;
};

/**
 * Instructor information.
 */
export type Instructor = {
	id: string;
	first_name: string | null;
	last_name: string | null;
	academic_email: string | null;
	personal_email: string | null;
	honorarium_status: string | null;
	mailing_address: string | null;
	institution: string | null;
};

export type FeatureFlags = {
	flags: Record<string, boolean>;
};

/**
 * Information about the current session.
 */
export type SessionState = {
	status: SessionStatus;
	error: string | null;
	token: SessionToken | null;
	instructor: Instructor | null;
	feature_flags?: FeatureFlags | null;
};
