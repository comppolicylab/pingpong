export type Course = {
	id: string;
	name?: string;
	status?: 'in_review' | 'accepted' | 'rejected';
	randomization?: 'control' | 'treatment';
	start_date?: string;
	enrollment_count?: number;
	preassessment_url?: string;
	pingpong_group_url?: string;
};

export type Courses = {
	courses: Course[];
};
