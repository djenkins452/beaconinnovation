import json
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.conf import settings

from .models import AdminTask


def validate_api_key(request):
    """Validate the Claude API key from request headers."""
    api_key = request.headers.get('X-Claude-API-Key')
    expected_key = getattr(settings, 'CLAUDE_API_KEY', None)

    if not expected_key:
        return False, 'API key not configured on server'

    if not api_key:
        return False, 'Missing X-Claude-API-Key header'

    if api_key != expected_key:
        return False, 'Invalid API key'

    return True, None


def api_error(message, status=400):
    """Return a JSON error response."""
    return JsonResponse({'error': message}, status=status)


@method_decorator(csrf_exempt, name='dispatch')
class ReadyTasksView(View):
    """
    GET /admin-console/api/claude/ready-tasks/

    Query parameters:
    - limit: Max number of tasks to return (default: 10)
    - auto_start: If 'true', mark the first returned task as in_progress
    """

    def get(self, request):
        # Validate API key
        valid, error = validate_api_key(request)
        if not valid:
            return api_error(error, status=401)

        # Parse query parameters
        try:
            limit = int(request.GET.get('limit', 10))
        except ValueError:
            limit = 10

        auto_start = request.GET.get('auto_start', '').lower() == 'true'

        # Get ready tasks (status=ready and no blocking dependencies)
        tasks = AdminTask.objects.filter(status='ready').order_by('-priority', 'created_at')

        # Filter out tasks with incomplete dependencies
        ready_tasks = [t for t in tasks if t.is_ready][:limit]

        # Auto-start the first task if requested
        if auto_start and ready_tasks:
            first_task = ready_tasks[0]
            first_task.status = 'in_progress'
            first_task.started_at = timezone.now()
            first_task.save(update_fields=['status', 'started_at', 'updated_at'])

        return JsonResponse({
            'tasks': [t.to_api_dict() for t in ready_tasks],
            'count': len(ready_tasks),
        })


@method_decorator(csrf_exempt, name='dispatch')
class TaskStatusView(View):
    """
    POST /admin-console/api/claude/tasks/<id>/status/

    Body (JSON):
    - status: New status ('ready', 'in_progress', 'done', 'blocked')
    - notes: Optional notes (especially for blocked tasks)
    """

    def post(self, request, task_id):
        # Validate API key
        valid, error = validate_api_key(request)
        if not valid:
            return api_error(error, status=401)

        # Get the task
        try:
            task = AdminTask.objects.get(id=task_id)
        except AdminTask.DoesNotExist:
            return api_error('Task not found', status=404)

        # Parse request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return api_error('Invalid JSON body')

        new_status = data.get('status')
        if not new_status:
            return api_error('Missing status field')

        valid_statuses = dict(AdminTask.STATUS_CHOICES).keys()
        if new_status not in valid_statuses:
            return api_error(f'Invalid status. Must be one of: {", ".join(valid_statuses)}')

        # Update task
        old_status = task.status
        task.status = new_status

        # Track timestamps
        if new_status == 'in_progress' and old_status != 'in_progress':
            task.started_at = timezone.now()
        elif new_status == 'done' and old_status != 'done':
            task.completed_at = timezone.now()

        # Optional notes
        if 'notes' in data:
            task.notes = data['notes']

        task.save(update_fields=['status', 'started_at', 'completed_at', 'notes', 'updated_at'])

        return JsonResponse({
            'success': True,
            'task': task.to_api_dict(),
            'message': f'Task status updated from {old_status} to {new_status}',
        })


@method_decorator(csrf_exempt, name='dispatch')
class TaskDetailView(View):
    """
    GET /admin-console/api/claude/tasks/<id>/

    Returns full task details.
    """

    def get(self, request, task_id):
        # Validate API key
        valid, error = validate_api_key(request)
        if not valid:
            return api_error(error, status=401)

        try:
            task = AdminTask.objects.get(id=task_id)
        except AdminTask.DoesNotExist:
            return api_error('Task not found', status=404)

        return JsonResponse({'task': task.to_api_dict()})


@method_decorator(csrf_exempt, name='dispatch')
class BulkImportView(View):
    """
    POST /admin-console/api/claude/tasks/import/

    Body (JSON):
    - tasks: List of task objects with title, description, priority (optional), phase (optional)
    """

    def post(self, request):
        # Validate API key
        valid, error = validate_api_key(request)
        if not valid:
            return api_error(error, status=401)

        # Parse request body
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return api_error('Invalid JSON body')

        tasks_data = data.get('tasks', [])
        if not tasks_data:
            return api_error('No tasks provided')

        if not isinstance(tasks_data, list):
            return api_error('Tasks must be a list')

        created_tasks = []
        errors = []

        for i, task_data in enumerate(tasks_data):
            try:
                task = AdminTask(
                    title=task_data.get('title', f'Imported Task {i + 1}'),
                    description=task_data.get('description', {}),
                    priority=task_data.get('priority', 2),
                    phase=task_data.get('phase', ''),
                    status='ready',
                )
                task.save()
                created_tasks.append(task.to_api_dict())
            except Exception as e:
                errors.append({
                    'index': i,
                    'title': task_data.get('title', f'Task {i + 1}'),
                    'error': str(e),
                })

        return JsonResponse({
            'success': len(errors) == 0,
            'created_count': len(created_tasks),
            'error_count': len(errors),
            'created_tasks': created_tasks,
            'errors': errors,
        })
