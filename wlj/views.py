# ==============================================================================
# File: views.py  
# Project: Beacon Innovations - WLJ Financial Dashboard
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Created: 2025-12-28
# ==============================================================================

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.http import FileResponse, JsonResponse

from .models import ServiceCost, FinancialProjection, CodebaseMetric, Document, DocumentDownload


def wlj_login(request):
    if request.user.is_authenticated:
        return redirect('wlj:dashboard')
    error = None
    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('username'), password=request.POST.get('password'))
        if user:
            login(request, user)
            return redirect('wlj:dashboard')
        error = 'Invalid credentials.'
    return render(request, 'wlj/login.html', {'error': error})


def wlj_logout(request):
    logout(request)
    return redirect('wlj:login')


@login_required(login_url='wlj:login')
def dashboard(request):
    return render(request, 'wlj/dashboard.html', {
        'latest_metrics': CodebaseMetric.objects.first(),
        'projections': FinancialProjection.objects.filter(scenario='base_case'),
        'service_costs': ServiceCost.objects.all()[:5],
        'documents': Document.objects.filter(is_current=True)[:5],
    })


@login_required(login_url='wlj:login')
def financials(request):
    scenarios = ['conservative', 'base_case', 'aggressive']
    data = {s: FinancialProjection.objects.filter(scenario=s).order_by('year') for s in scenarios}
    return render(request, 'wlj/financials.html', {'projections_by_scenario': data})


@login_required(login_url='wlj:login')
def service_costs_view(request):
    return render(request, 'wlj/service_costs.html', {'all_costs': ServiceCost.objects.all()})


@login_required(login_url='wlj:login')
def codebase_metrics(request):
    metrics = CodebaseMetric.objects.all()[:10]
    return render(request, 'wlj/codebase_metrics.html', {'metrics': metrics, 'latest': metrics.first() if metrics else None})


@login_required(login_url='wlj:login')
def data_room(request):
    return render(request, 'wlj/data_room.html', {'all_documents': Document.objects.filter(is_current=True)})


@login_required(login_url='wlj:login')
def download_document(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    DocumentDownload.objects.create(document=doc, user=request.user, ip_address=request.META.get('REMOTE_ADDR'))
    doc.download_count += 1
    doc.save()
    return FileResponse(doc.file.open('rb'), as_attachment=True, filename=doc.file.name.split('/')[-1])


@login_required(login_url='wlj:login')
def api_projections(request):
    data = {'scenarios': {}}
    for p in FinancialProjection.objects.all():
        if p.scenario not in data['scenarios']:
            data['scenarios'][p.scenario] = []
        data['scenarios'][p.scenario].append({'year': p.year, 'users': p.paying_users, 'revenue': float(p.annual_revenue), 'profit': float(p.net_profit)})
    return JsonResponse(data)
