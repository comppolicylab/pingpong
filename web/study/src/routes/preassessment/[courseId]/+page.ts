import { getPreAssessmentStudents } from '$lib/api/client';
import type { PreAssessmentStudent } from '$lib/api/types';
import { explodeResponse } from '$lib/api/utils';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch, parent }) => {
	const { courses } = await parent();
	const courseId = params.courseId;

	let preAssessmentStudents: PreAssessmentStudent[] = [];
	preAssessmentStudents = await getPreAssessmentStudents(fetch, courseId)
		.then(explodeResponse)
		.then((res) => res.students);

	const title = courses.find((course) => course.id === courseId)?.name || 'Unknown Course';
	const completionRateTarget = courses.find(
		(course) => course.id === courseId
	)?.completion_rate_target;
	const enrollmentCount = courses.find((course) => course.id === courseId)?.enrollment_count;
	const preAssessmentStudentCount = courses.find(
		(course) => course.id === courseId
	)?.preassessment_student_count;
	return {
		title,
		preAssessmentStudents,
		completionRateTarget,
		enrollmentCount,
		preAssessmentStudentCount
	};
};
