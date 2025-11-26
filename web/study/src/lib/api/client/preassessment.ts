import { DELETE, GET, type Fetcher } from '../utils';
import type { AssessmentStudents } from '../types';

export const getPreAssessmentStudents = async (f: Fetcher, courseId: string) => {
	return await GET<never, AssessmentStudents>(f, `preassessment/${courseId}/students`);
};

export const deletePreAssessmentStudent = async (
	f: Fetcher,
	courseId: string,
	submissionId: string
) => {
	return await DELETE<never, { status: string }>(
		f,
		`preassessment/${courseId}/students/${submissionId}`
	);
};
