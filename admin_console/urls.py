from django.urls import path
from . import views
from . import api_views

app_name = 'admin_console'

urlpatterns = [
    # Admin UI views
    path('', views.dashboard, name='dashboard'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/create/', views.task_create, name='task_create'),
    path('tasks/<uuid:task_id>/', views.task_detail, name='task_detail'),
    path('tasks/<uuid:task_id>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<uuid:task_id>/delete/', views.task_delete, name='task_delete'),
    path('tasks/import/', views.task_import, name='task_import'),

    # Claude API endpoints
    path('api/claude/ready-tasks/', api_views.ReadyTasksView.as_view(), name='api_ready_tasks'),
    path('api/claude/tasks/<uuid:task_id>/', api_views.TaskDetailView.as_view(), name='api_task_detail'),
    path('api/claude/tasks/<uuid:task_id>/status/', api_views.TaskStatusView.as_view(), name='api_task_status'),
    path('api/claude/tasks/import/', api_views.BulkImportView.as_view(), name='api_bulk_import'),
]
