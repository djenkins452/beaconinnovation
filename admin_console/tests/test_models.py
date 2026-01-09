from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from admin_console.models import AdminTask


class AdminTaskModelTest(TestCase):
    """Tests for the AdminTask model."""

    def setUp(self):
        self.valid_description = {
            'objective': 'Test objective',
            'inputs': ['input1', 'input2'],
            'actions': ['action1', 'action2'],
            'output': 'Expected output'
        }

    def test_create_valid_task(self):
        """Test creating a task with valid data."""
        task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description
        )
        self.assertEqual(task.title, 'Test Task')
        self.assertEqual(task.status, 'ready')
        self.assertEqual(task.priority, 2)

    def test_missing_required_keys(self):
        """Test that missing required keys raise ValidationError."""
        invalid_description = {
            'objective': 'Test',
            'inputs': [],
            # missing actions and output
        }
        task = AdminTask(title='Test', description=invalid_description)
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_empty_objective(self):
        """Test that empty objective raises ValidationError."""
        invalid_description = {
            'objective': '',
            'inputs': [],
            'actions': ['action1'],
            'output': 'output'
        }
        task = AdminTask(title='Test', description=invalid_description)
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_empty_actions(self):
        """Test that empty actions raises ValidationError."""
        invalid_description = {
            'objective': 'objective',
            'inputs': [],
            'actions': [],
            'output': 'output'
        }
        task = AdminTask(title='Test', description=invalid_description)
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_empty_output(self):
        """Test that empty output raises ValidationError."""
        invalid_description = {
            'objective': 'objective',
            'inputs': [],
            'actions': ['action1'],
            'output': ''
        }
        task = AdminTask(title='Test', description=invalid_description)
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_inputs_must_be_list(self):
        """Test that inputs must be a list."""
        invalid_description = {
            'objective': 'objective',
            'inputs': 'not a list',
            'actions': ['action1'],
            'output': 'output'
        }
        task = AdminTask(title='Test', description=invalid_description)
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_actions_must_be_list(self):
        """Test that actions must be a list."""
        invalid_description = {
            'objective': 'objective',
            'inputs': [],
            'actions': 'not a list',
            'output': 'output'
        }
        task = AdminTask(title='Test', description=invalid_description)
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_description_must_be_dict(self):
        """Test that description must be a dictionary."""
        task = AdminTask(title='Test', description='not a dict')
        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_is_ready_property(self):
        """Test the is_ready property."""
        task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description,
            status='ready'
        )
        self.assertTrue(task.is_ready)

        task.status = 'in_progress'
        task.save()
        self.assertFalse(task.is_ready)

    def test_is_ready_with_dependency(self):
        """Test is_ready when task has a dependency."""
        parent_task = AdminTask.objects.create(
            title='Parent Task',
            description=self.valid_description,
            status='ready'
        )
        child_task = AdminTask.objects.create(
            title='Child Task',
            description=self.valid_description,
            status='ready',
            depends_on=parent_task
        )

        # Child not ready because parent is not done
        self.assertFalse(child_task.is_ready)

        # Complete parent
        parent_task.status = 'done'
        parent_task.save()

        # Refresh child from db
        child_task.refresh_from_db()
        self.assertTrue(child_task.is_ready)

    def test_to_api_dict(self):
        """Test the to_api_dict method."""
        task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description,
            phase='Phase 1'
        )
        api_dict = task.to_api_dict()

        self.assertEqual(api_dict['title'], 'Test Task')
        self.assertEqual(api_dict['description'], self.valid_description)
        self.assertEqual(api_dict['status'], 'ready')
        self.assertEqual(api_dict['phase'], 'Phase 1')
        self.assertIn('id', api_dict)
        self.assertIn('created_at', api_dict)

    def test_str_representation(self):
        """Test the string representation."""
        task = AdminTask.objects.create(
            title='Test Task',
            description=self.valid_description
        )
        self.assertEqual(str(task), '[Ready] Test Task')

    def test_priority_choices(self):
        """Test all priority choices."""
        for priority_value, priority_label in AdminTask.PRIORITY_CHOICES:
            task = AdminTask.objects.create(
                title=f'Priority {priority_value} Task',
                description=self.valid_description,
                priority=priority_value
            )
            self.assertEqual(task.priority, priority_value)

    def test_status_choices(self):
        """Test all status choices."""
        for status_value, status_label in AdminTask.STATUS_CHOICES:
            task = AdminTask.objects.create(
                title=f'{status_value} Task',
                description=self.valid_description,
                status=status_value
            )
            self.assertEqual(task.status, status_value)
