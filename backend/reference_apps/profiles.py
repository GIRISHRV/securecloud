from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    id: str
    label: str
    kind: str = "text"
    required: bool = True
    max_length: int = 100
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceSpec:
    id: str
    singular: str
    label: str
    description: str
    fields: tuple[FieldSpec, ...]


@dataclass(frozen=True)
class ProfileSpec:
    id: str
    name: str
    description: str
    resources: tuple[ResourceSpec, ...]

    def resource(self, resource_id: str) -> ResourceSpec | None:
        return next((resource for resource in self.resources if resource.id == resource_id), None)


def field(field_id: str, label: str, *, kind: str = "text", max_length: int = 100,
          options: tuple[str, ...] = ()) -> FieldSpec:
    return FieldSpec(field_id, label, kind, True, max_length, options)


PROFILES: dict[str, ProfileSpec] = {
    "college": ProfileSpec(
        id="college",
        name="School Management",
        description="Manage admissions, faculty, courses, and daily attendance.",
        resources=(
            ResourceSpec("students", "student", "Students", "Student admissions and guardian contacts.", (
                field("full_name", "Full name"), field("admission_number", "Admission number", max_length=30),
                field("grade", "Class / grade", max_length=30),
                field("guardian_phone", "Guardian phone", kind="tel", max_length=20),
            )),
            ResourceSpec("faculty", "faculty member", "Faculty", "Teaching staff and subject assignments.", (
                field("full_name", "Full name"), field("employee_id", "Employee ID", max_length=30),
                field("subject", "Subject", max_length=60), field("email", "Email", kind="email", max_length=120),
            )),
            ResourceSpec("courses", "course", "Courses", "Course ownership and credit allocation.", (
                field("code", "Course code", max_length=20), field("title", "Course title"),
                field("faculty_name", "Faculty member"),
                field("credits", "Credits", kind="select", options=("1", "2", "3", "4", "5")),
            )),
            ResourceSpec("attendance", "attendance entry", "Attendance", "Daily student attendance by class.", (
                field("student_name", "Student name"), field("class_name", "Class", max_length=30),
                field("attendance_date", "Date", kind="date", max_length=10),
                field("status", "Status", kind="select", options=("Present", "Absent", "Late")),
            )),
        ),
    ),
    "hospital": ProfileSpec(
        id="hospital",
        name="Hospital Management",
        description="Manage patients, clinical staff, and appointments.",
        resources=(
            ResourceSpec("patients", "patient", "Patients", "Patient registration and contact details.", (
                field("full_name", "Full name"), field("patient_number", "Patient number", max_length=30),
                field("date_of_birth", "Date of birth", kind="date", max_length=10),
                field("phone", "Phone", kind="tel", max_length=20),
            )),
            ResourceSpec("doctors", "doctor", "Doctors", "Doctors and their clinical specialties.", (
                field("full_name", "Full name"), field("employee_id", "Employee ID", max_length=30),
                field("specialty", "Specialty", max_length=80), field("email", "Email", kind="email", max_length=120),
            )),
            ResourceSpec("appointments", "appointment", "Appointments", "Patient appointments and consultation status.", (
                field("patient_name", "Patient name"), field("doctor_name", "Doctor name"),
                field("scheduled_at", "Date and time", kind="datetime-local", max_length=25),
                field("status", "Status", kind="select", options=("Scheduled", "Completed", "Cancelled")),
            )),
        ),
    ),
}


def get_profile(profile_id: str) -> ProfileSpec:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        allowed = ", ".join(sorted(PROFILES))
        raise ValueError(f"APP_PROFILE must be one of: {allowed}") from exc
