"""Core HR console views (Phase 1 — deliberately small).

Employee: list/search/view/add/edit. Reference entities: list/add/edit/
activate-deactivate. All gated by Phase 0 access control; all writes routed
through the service layer so they are validated and audited.
"""
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from aegis.core.auth.access import require_platform_access
from aegis.core_hr import services
from aegis.core_hr.forms import REFERENCE_FORMS, EmployeeForm, scope_modelchoice_fields
from aegis.core_hr.models import Employee


# --- Employee ---------------------------------------------------------------

@require_platform_access
def employee_list(request):
    employees = Employee.objects.select_related(
        'company', 'department', 'job', 'location', 'employment_status', 'employee_type', 'manager'
    )
    query = request.GET.get('q', '').strip()
    if query:
        from django.db.models import Q
        employees = employees.filter(
            Q(employee_number__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(preferred_name__icontains=query)
        )
    return render(request, 'aegis/core_hr/employee_list.html',
                  {'employees': employees, 'query': query})


@require_platform_access
def employee_detail(request, pk):
    employee = get_object_or_404(Employee.objects.select_related(
        'company', 'department', 'job', 'location', 'employment_status', 'employee_type', 'manager'
    ), pk=pk)
    return render(request, 'aegis/core_hr/employee_detail.html', {'employee': employee})


@require_platform_access
def employee_create(request):
    form = EmployeeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data)
        try:
            emp = services.create_employee(
                tenant=request.platform_tenant, actor=request.platform_user, request=request, **data)
            return redirect(reverse('platform:core_hr:employee_detail', args=[emp.pk]))
        except Exception as exc:  # service-layer validation → surface on the form
            form.add_error(None, str(exc))
    return render(request, 'aegis/core_hr/employee_form.html', {'form': form, 'mode': 'Add'})


@require_platform_access
def employee_edit(request, pk):
    employee = get_object_or_404(Employee.objects.all(), pk=pk)
    form = EmployeeForm(request.POST or None, instance=employee)
    if request.method == 'POST' and form.is_valid():
        try:
            services.update_employee(
                employee, actor=request.platform_user, request=request, **form.cleaned_data)
            return redirect(reverse('platform:core_hr:employee_detail', args=[employee.pk]))
        except Exception as exc:
            form.add_error(None, str(exc))
    return render(request, 'aegis/core_hr/employee_form.html',
                  {'form': form, 'mode': 'Edit', 'employee': employee})


# --- Reference entities (generic) ------------------------------------------

def _reference_or_404(slug):
    if slug not in REFERENCE_FORMS:
        from django.http import Http404
        raise Http404('Unknown reference type')
    return REFERENCE_FORMS[slug]


@require_platform_access
def reference_list(request, slug):
    model, _fields, label = _reference_or_404(slug)
    objects = model.objects.all()
    return render(request, 'aegis/core_hr/reference_list.html',
                  {'objects': objects, 'label': label, 'slug': slug})


@require_platform_access
def reference_create(request, slug):
    model, fields, label = _reference_or_404(slug)
    FormClass = modelform_factory(model, fields=fields)
    form = FormClass(request.POST or None)
    scope_modelchoice_fields(form)
    if request.method == 'POST' and form.is_valid():
        try:
            services.create_reference(model, tenant=request.platform_tenant,
                                      actor=request.platform_user, request=request, **form.cleaned_data)
            return redirect(reverse('platform:core_hr:reference_list', args=[slug]))
        except Exception as exc:
            form.add_error(None, str(exc))
    return render(request, 'aegis/core_hr/reference_form.html',
                  {'form': form, 'label': label, 'slug': slug, 'mode': 'Add'})


@require_platform_access
def reference_edit(request, slug, pk):
    model, fields, label = _reference_or_404(slug)
    obj = get_object_or_404(model.objects.all(), pk=pk)
    FormClass = modelform_factory(model, fields=fields)
    form = FormClass(request.POST or None, instance=obj)
    scope_modelchoice_fields(form)
    if request.method == 'POST' and form.is_valid():
        try:
            services.update_reference(obj, actor=request.platform_user, request=request,
                                      **form.cleaned_data)
            return redirect(reverse('platform:core_hr:reference_list', args=[slug]))
        except Exception as exc:
            form.add_error(None, str(exc))
    return render(request, 'aegis/core_hr/reference_form.html',
                  {'form': form, 'label': label, 'slug': slug, 'mode': 'Edit', 'obj': obj})


@require_platform_access
def reference_toggle_active(request, slug, pk):
    model, _fields, _label = _reference_or_404(slug)
    obj = get_object_or_404(model.objects.all(), pk=pk)
    if request.method == 'POST':
        services.set_reference_active(obj, is_active=not obj.is_active,
                                      actor=request.platform_user, request=request)
    return redirect(reverse('platform:core_hr:reference_list', args=[slug]))
