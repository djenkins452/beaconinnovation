"""Generic Core HR default reference data (tenant-parameterized, no Beacon assumptions).

Beacon-specific values are seed *inputs*, not schema. Any Tenant #2 can establish
its own reference data the same way.
"""
from aegis.core_hr.models import EmployeeClassification, SystemStatusCategory

# (code, label, system_category)
DEFAULT_EMPLOYMENT_STATUSES = [
    ('A', 'Active', SystemStatusCategory.ACTIVE),
    ('LOA', 'Leave of Absence', SystemStatusCategory.LEAVE),
    ('TERM', 'Terminated', SystemStatusCategory.TERMINATED),
]

# (code, label, classification)
DEFAULT_EMPLOYEE_TYPES = [
    ('FT', 'Regular Full-Time', EmployeeClassification.EMPLOYEE),
    ('PT', 'Regular Part-Time', EmployeeClassification.EMPLOYEE),
    ('PRN', 'PRN', EmployeeClassification.EMPLOYEE),
    ('TEMP', 'Temporary', EmployeeClassification.EMPLOYEE),
    ('CONT', 'Contractor', EmployeeClassification.CONTINGENT),
    ('INT', 'Intern', EmployeeClassification.EMPLOYEE),
]
