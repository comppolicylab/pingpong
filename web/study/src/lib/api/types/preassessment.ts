export type PreAssessmentStudent = {
	id: string;
	first_name?: string;
	last_name?: string;
	email?: string;
	submission_date?: string;
};

export type PreAssessmentStudents = {
	students: PreAssessmentStudent[];
};
