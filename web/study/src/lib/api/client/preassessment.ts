import { GET, type Fetcher } from '../utils';
import type { PreAssessmentStudents } from '../types';

export const getPreAssessmentStudents = async (f: Fetcher, courseId: string) => {
	return await GET<never, PreAssessmentStudents>(f, `preassessment/${courseId}/students`);
};
