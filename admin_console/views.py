import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseNotAllowed

from .models import AdminTask
from .forms import AdminTaskForm, TaskImportForm


@login_required
def dashboard(request):
    """Admin console dashboard showing task overview."""
    tasks_by_status = {
        'ready': AdminTask.objects.filter(status='ready').count(),
        'in_progress': AdminTask.objects.filter(status='in_progress').count(),
        'done': AdminTask.objects.filter(status='done').count(),
        'blocked': AdminTask.objects.filter(status='blocked').count(),
    }

    recent_tasks = AdminTask.objects.all()[:10]

    context = {
        'tasks_by_status': tasks_by_status,
        'recent_tasks': recent_tasks,
        'total_tasks': sum(tasks_by_status.values()),
    }
    return render(request, 'admin_console/dashboard.html', context)


@login_required
def task_list(request):
    """List all tasks with filtering."""
    status_filter = request.GET.get('status', '')
    phase_filter = request.GET.get('phase', '')

    tasks = AdminTask.objects.all()

    if status_filter:
        tasks = tasks.filter(status=status_filter)
    if phase_filter:
        tasks = tasks.filter(phase=phase_filter)

    # Get unique phases for filter dropdown
    phases = AdminTask.objects.values_list('phase', flat=True).distinct()
    phases = [p for p in phases if p]

    context = {
        'tasks': tasks,
        'status_filter': status_filter,
        'phase_filter': phase_filter,
        'phases': phases,
        'status_choices': AdminTask.STATUS_CHOICES,
    }
    return render(request, 'admin_console/task_list.html', context)


@login_required
def task_detail(request, task_id):
    """View task details."""
    task = get_object_or_404(AdminTask, id=task_id)
    context = {'task': task}
    return render(request, 'admin_console/task_detail.html', context)


@login_required
def task_create(request):
    """Create a new task."""
    if request.method == 'POST':
        form = AdminTaskForm(request.POST)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.save()
            messages.success(request, f'Task "{task.title}" created successfully.')
            return redirect('admin_console:task_detail', task_id=task.id)
    else:
        form = AdminTaskForm()

    context = {'form': form, 'action': 'Create'}
    return render(request, 'admin_console/task_form.html', context)


@login_required
def task_edit(request, task_id):
    """Edit an existing task."""
    task = get_object_or_404(AdminTask, id=task_id)

    if request.method == 'POST':
        form = AdminTaskForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            messages.success(request, f'Task "{task.title}" updated successfully.')
            return redirect('admin_console:task_detail', task_id=task.id)
    else:
        form = AdminTaskForm(instance=task)

    context = {'form': form, 'task': task, 'action': 'Edit'}
    return render(request, 'admin_console/task_form.html', context)


@login_required
def task_delete(request, task_id):
    """Delete a task."""
    task = get_object_or_404(AdminTask, id=task_id)

    if request.method == 'POST':
        title = task.title
        task.delete()
        messages.success(request, f'Task "{title}" deleted successfully.')
        return redirect('admin_console:task_list')

    context = {'task': task}
    return render(request, 'admin_console/task_confirm_delete.html', context)


@login_required
def task_import(request):
    """Import tasks from JSON file."""
    if request.method == 'POST':
        form = TaskImportForm(request.POST, request.FILES)
        if form.is_valid():
            json_file = request.FILES['json_file']
            try:
                data = json.load(json_file)
                tasks_data = data if isinstance(data, list) else data.get('tasks', [])

                created_count = 0
                errors = []

                for i, task_data in enumerate(tasks_data):
                    try:
                        task = AdminTask(
                            title=task_data.get('title', f'Imported Task {i + 1}'),
                            description=task_data.get('description', {}),
                            priority=task_data.get('priority', 2),
                            phase=task_data.get('phase', ''),
                            status='ready',
                            created_by=request.user,
                        )
                        task.save()
                        created_count += 1
                    except Exception as e:
                        errors.append(f"Task {i + 1}: {str(e)}")

                if created_count > 0:
                    messages.success(request, f'Successfully imported {created_count} task(s).')
                if errors:
                    for error in errors:
                        messages.error(request, error)

                return redirect('admin_console:task_list')

            except json.JSONDecodeError:
                messages.error(request, 'Invalid JSON file.')
    else:
        form = TaskImportForm()

    context = {'form': form}
    return render(request, 'admin_console/task_import.html', context)
