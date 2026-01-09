import json
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from admin_console.models import AdminTask


@override_settings(CLAUDE_API_KEY='test-api-key')
class APIAuthenticationTest(TestCase):
    """Tests for API key authentication."""

    def setUp(self):
        self.client = Client()
        self.valid_description = {
            'objective': 'Test objective',
            'inputs': [],
            'actions': ['action1'],
            'output': 'Expected output'
        }
        self.task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description
        )

    def test_missing_api_key(self):
        """Test that missing API key returns 401."""
        response = self.client.get(reverse('admin_console:api_ready_tasks'))
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.content)
        self.assertIn('error', data)

    def test_invalid_api_key(self):
        """Test that invalid API key returns 401."""
        response = self.client.get(
            reverse('admin_console:api_ready_tasks'),
            HTTP_X_CLAUDE_API_KEY='wrong-key'
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_api_key(self):
        """Test that valid API key grants access."""
        response = self.client.get(
            reverse('admin_console:api_ready_tasks'),
            HTTP_X_CLAUDE_API_KEY='test-api-key'
        )
        self.assertEqual(response.status_code, 200)


@override_settings(CLAUDE_API_KEY='test-api-key')
class ReadyTasksAPITest(TestCase):
    """Tests for the ready-tasks endpoint."""

    def setUp(self):
        self.client = Client()
        self.headers = {'HTTP_X_CLAUDE_API_KEY': 'test-api-key'}
        self.valid_description = {
            'objective': 'Test objective',
            'inputs': [],
            'actions': ['action1'],
            'output': 'Expected output'
        }

    def test_get_ready_tasks(self):
        """Test fetching ready tasks."""
        AdminTask.objects.create(
            title='Ready Task',
            description=self.valid_description,
            status='ready'
        )
        AdminTask.objects.create(
            title='In Progress Task',
            description=self.valid_description,
            status='in_progress'
        )

        response = self.client.get(
            reverse('admin_console:api_ready_tasks'),
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertEqual(data['count'], 1)
        self.assertEqual(data['tasks'][0]['title'], 'Ready Task')

    def test_get_ready_tasks_with_limit(self):
        """Test limiting the number of returned tasks."""
        for i in range(5):
            AdminTask.objects.create(
                title=f'Task {i}',
                description=self.valid_description,
                status='ready'
            )

        response = self.client.get(
            reverse('admin_console:api_ready_tasks') + '?limit=2',
            **self.headers
        )
        data = json.loads(response.content)
        self.assertEqual(data['count'], 2)

    def test_auto_start_marks_task_in_progress(self):
        """Test that auto_start=true marks the first task as in_progress."""
        task = AdminTask.objects.create(
            title='Ready Task',
            description=self.valid_description,
            status='ready'
        )

        response = self.client.get(
            reverse('admin_console:api_ready_tasks') + '?auto_start=true',
            **self.headers
        )
        data = json.loads(response.content)

        task.refresh_from_db()
        self.assertEqual(task.status, 'in_progress')
        self.assertIsNotNone(task.started_at)

    def test_priority_ordering(self):
        """Test that tasks are ordered by priority (highest first)."""
        AdminTask.objects.create(
            title='Low Priority',
            description=self.valid_description,
            status='ready',
            priority=1
        )
        AdminTask.objects.create(
            title='High Priority',
            description=self.valid_description,
            status='ready',
            priority=3
        )

        response = self.client.get(
            reverse('admin_console:api_ready_tasks'),
            **self.headers
        )
        data = json.loads(response.content)

        self.assertEqual(data['tasks'][0]['title'], 'High Priority')

    def test_dependency_filtering(self):
        """Test that tasks with incomplete dependencies are filtered out."""
        parent = AdminTask.objects.create(
            title='Parent Task',
            description=self.valid_description,
            status='ready'
        )
        child = AdminTask.objects.create(
            title='Child Task',
            description=self.valid_description,
            status='ready',
            depends_on=parent
        )

        response = self.client.get(
            reverse('admin_console:api_ready_tasks'),
            **self.headers
        )
        data = json.loads(response.content)

        # Only parent should be returned since child has incomplete dependency
        titles = [t['title'] for t in data['tasks']]
        self.assertIn('Parent Task', titles)
        self.assertNotIn('Child Task', titles)


@override_settings(CLAUDE_API_KEY='test-api-key')
class TaskStatusAPITest(TestCase):
    """Tests for the task status update endpoint."""

    def setUp(self):
        self.client = Client()
        self.headers = {'HTTP_X_CLAUDE_API_KEY': 'test-api-key'}
        self.valid_description = {
            'objective': 'Test objective',
            'inputs': [],
            'actions': ['action1'],
            'output': 'Expected output'
        }
        self.task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description,
            status='ready'
        )

    def test_update_status_to_in_progress(self):
        """Test updating task status to in_progress."""
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[self.task.id]),
            data=json.dumps({'status': 'in_progress'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')
        self.assertIsNotNone(self.task.started_at)

    def test_update_status_to_done(self):
        """Test updating task status to done."""
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[self.task.id]),
            data=json.dumps({'status': 'done'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'done')
        self.assertIsNotNone(self.task.completed_at)

    def test_update_status_with_notes(self):
        """Test updating task status with notes."""
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[self.task.id]),
            data=json.dumps({'status': 'blocked', 'notes': 'Blocked by dependency'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        self.task.refresh_from_db()
        self.assertEqual(self.task.notes, 'Blocked by dependency')

    def test_invalid_status(self):
        """Test that invalid status returns error."""
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[self.task.id]),
            data=json.dumps({'status': 'invalid_status'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_status(self):
        """Test that missing status returns error."""
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[self.task.id]),
            data=json.dumps({}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_task_not_found(self):
        """Test that non-existent task returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[fake_id]),
            data=json.dumps({'status': 'done'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_json(self):
        """Test that invalid JSON returns error."""
        response = self.client.post(
            reverse('admin_console:api_task_status', args=[self.task.id]),
            data='not valid json',
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)


@override_settings(CLAUDE_API_KEY='test-api-key')
class TaskDetailAPITest(TestCase):
    """Tests for the task detail endpoint."""

    def setUp(self):
        self.client = Client()
        self.headers = {'HTTP_X_CLAUDE_API_KEY': 'test-api-key'}
        self.valid_description = {
            'objective': 'Test objective',
            'inputs': [],
            'actions': ['action1'],
            'output': 'Expected output'
        }
        self.task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description
        )

    def test_get_task_detail(self):
        """Test getting task details."""
        response = self.client.get(
            reverse('admin_console:api_task_detail', args=[self.task.id]),
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertEqual(data['task']['title'], 'Test Task')
        self.assertEqual(data['task']['description'], self.valid_description)

    def test_task_not_found(self):
        """Test that non-existent task returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.get(
            reverse('admin_console:api_task_detail', args=[fake_id]),
            **self.headers
        )
        self.assertEqual(response.status_code, 404)


@override_settings(CLAUDE_API_KEY='test-api-key')
class BulkImportAPITest(TestCase):
    """Tests for the bulk import endpoint."""

    def setUp(self):
        self.client = Client()
        self.headers = {'HTTP_X_CLAUDE_API_KEY': 'test-api-key'}

    def test_import_single_task(self):
        """Test importing a single task."""
        tasks_data = {
            'tasks': [{
                'title': 'Imported Task',
                'description': {
                    'objective': 'Test',
                    'inputs': [],
                    'actions': ['action1'],
                    'output': 'output'
                }
            }]
        }

        response = self.client.post(
            reverse('admin_console:api_bulk_import'),
            data=json.dumps(tasks_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        self.assertTrue(data['success'])
        self.assertEqual(data['created_count'], 1)
        self.assertEqual(AdminTask.objects.count(), 1)

    def test_import_multiple_tasks(self):
        """Test importing multiple tasks."""
        tasks_data = {
            'tasks': [
                {
                    'title': f'Task {i}',
                    'description': {
                        'objective': 'Test',
                        'inputs': [],
                        'actions': ['action1'],
                        'output': 'output'
                    }
                }
                for i in range(3)
            ]
        }

        response = self.client.post(
            reverse('admin_console:api_bulk_import'),
            data=json.dumps(tasks_data),
            content_type='application/json',
            **self.headers
        )
        data = json.loads(response.content)

        self.assertEqual(data['created_count'], 3)
        self.assertEqual(AdminTask.objects.count(), 3)

    def test_import_with_invalid_task(self):
        """Test that invalid tasks are reported as errors."""
        tasks_data = {
            'tasks': [
                {
                    'title': 'Valid Task',
                    'description': {
                        'objective': 'Test',
                        'inputs': [],
                        'actions': ['action1'],
                        'output': 'output'
                    }
                },
                {
                    'title': 'Invalid Task',
                    'description': {
                        'objective': '',  # Invalid: empty objective
                        'inputs': [],
                        'actions': ['action1'],
                        'output': 'output'
                    }
                }
            ]
        }

        response = self.client.post(
            reverse('admin_console:api_bulk_import'),
            data=json.dumps(tasks_data),
            content_type='application/json',
            **self.headers
        )
        data = json.loads(response.content)

        self.assertFalse(data['success'])
        self.assertEqual(data['created_count'], 1)
        self.assertEqual(data['error_count'], 1)

    def test_import_empty_tasks_list(self):
        """Test that empty tasks list returns error."""
        response = self.client.post(
            reverse('admin_console:api_bulk_import'),
            data=json.dumps({'tasks': []}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_import_with_priority_and_phase(self):
        """Test importing tasks with priority and phase."""
        tasks_data = {
            'tasks': [{
                'title': 'Task with extras',
                'description': {
                    'objective': 'Test',
                    'inputs': [],
                    'actions': ['action1'],
                    'output': 'output'
                },
                'priority': 3,
                'phase': 'Phase 1'
            }]
        }

        response = self.client.post(
            reverse('admin_console:api_bulk_import'),
            data=json.dumps(tasks_data),
            content_type='application/json',
            **self.headers
        )
        data = json.loads(response.content)

        task = AdminTask.objects.first()
        self.assertEqual(task.priority, 3)
        self.assertEqual(task.phase, 'Phase 1')
