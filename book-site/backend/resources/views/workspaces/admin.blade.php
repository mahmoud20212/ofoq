@extends('layouts.app')

@section('title', 'لوحة إدارة المنظومة — ' . config('app.name'))

@section('content')
<main class="workspace-page">
    <div class="container-ofuq workspace-shell">
        <div class="workspace-heading">
            <div>
                <span class="platform-pill" style="background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.35); color: #fca5a5;">
                    <i class="fas fa-crown"></i>
                    <span>إدارة المنظومة الشاملة</span>
                </span>
                <h1>لوحة <span class="gradient-text">الإدارة المركزية</span></h1>
                <p>مرحباً بك، <strong>{{ Auth::user()->name }}</strong> — إدارة المستخدمين، اعتماد الطلبات، والمحتوى.</p>
            </div>
            <div class="d-flex gap-2">
                <a href="{{ route('moderation.workspace') }}" class="button button--secondary">
                    <i class="fas fa-shield-alt"></i>
                    <span>لوحة المشرف</span>
                </a>
            </div>
        </div>

        @if(session()->has('success'))
            <div class="workspace-notice mt-4">
                <i class="fas fa-check-circle"></i>
                <span>{{ session()->get('success') }}</span>
            </div>
        @endif

        <!-- Global Ecosystem KPIs -->
        <div class="row g-4 my-4">
            <div class="col-sm-6 col-lg-3">
                <div class="glass-card p-4 d-flex align-items-center gap-3" style="border-radius: 20px;">
                    <div class="p-3 rounded-4" style="background: rgba(36, 117, 233, 0.2); color: var(--sky);">
                        <i class="fas fa-users fa-2x"></i>
                    </div>
                    <div>
                        <small class="text-muted d-block">إجمالي المستخدمين</small>
                        <strong class="text-white fs-3 fw-bold">{{ $usersCount }}</strong>
                    </div>
                </div>
            </div>

            <div class="col-sm-6 col-lg-3">
                <div class="glass-card p-4 d-flex align-items-center gap-3" style="border-radius: 20px;">
                    <div class="p-3 rounded-4" style="background: rgba(98, 70, 217, 0.2); color: var(--lavender);">
                        <i class="fas fa-book-open fa-2x"></i>
                    </div>
                    <div>
                        <small class="text-muted d-block">إجمالي الكتب والمراجع</small>
                        <strong class="text-white fs-3 fw-bold">{{ $booksCount }}</strong>
                    </div>
                </div>
            </div>

            <div class="col-sm-6 col-lg-3">
                <div class="glass-card p-4 d-flex align-items-center gap-3" style="border-radius: 20px;">
                    <div class="p-3 rounded-4" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">
                        <i class="fas fa-bolt fa-2x"></i>
                    </div>
                    <div>
                        <small class="text-muted d-block">النداءات العاجلة</small>
                        <strong class="text-white fs-3 fw-bold">{{ $urgentCount }}</strong>
                    </div>
                </div>
            </div>

            <div class="col-sm-6 col-lg-3">
                <div class="glass-card p-4 d-flex align-items-center gap-3" style="border-radius: 20px;">
                    <div class="p-3 rounded-4" style="background: rgba(234, 179, 8, 0.2); color: #fde047;">
                        <i class="fas fa-clipboard-check fa-2x"></i>
                    </div>
                    <div>
                        <small class="text-muted d-block">طلبات الأدوار المعلقة</small>
                        <strong class="text-white fs-3 fw-bold">{{ $applications->where('status', 'pending')->count() }}</strong>
                    </div>
                </div>
            </div>
        </div>

        <div class="workspace-grid">
            <div class="workspace-main">
                <div class="d-flex flex-wrap justify-content-between align-items-center mb-4 gap-2">
                    <h3 class="text-white fw-bold fs-5 m-0">طلبات اعتماد المعلمين والمؤلفين (SSO-09)</h3>
                    <span class="text-muted small">قيد الانتظار: {{ $applications->where('status', 'pending')->count() }}</span>
                </div>

                @if($applications->isEmpty())
                    <div class="text-center py-5">
                        <i class="fas fa-clipboard-list fa-3x text-muted mb-3" style="opacity: 0.5;"></i>
                        <p class="text-muted">لا توجد طلبات أدوار حالياً.</p>
                    </div>
                @else
                    <div class="workspace-list">
                        @foreach($applications as $app)
                            <article style="display: flex; flex-wrap: wrap; align-items: center; gap: 16px; padding: 16px 0; border-bottom: 1px solid var(--border);">
                                <span class="workspace-list__icon" style="background: {{ $app->role_requested === 'author' ? 'rgba(36, 117, 233, 0.15)' : 'rgba(98, 70, 217, 0.15)' }}; color: {{ $app->role_requested === 'author' ? 'var(--sky)' : 'var(--lavender)' }};">
                                    <i class="fas {{ $app->role_requested === 'author' ? 'fa-feather-alt' : 'fa-chalkboard-teacher' }}"></i>
                                </span>
                                <div style="flex: 1; min-width: 200px;">
                                    <small class="text-muted">{{ $app->user->name ?? 'مستخدم' }} ({{ $app->user->email ?? '' }}) · {{ $app->created_at->format('Y-m-d') }}</small>
                                    <h3 class="fs-6 mb-1">طلب دور: {{ $app->role_requested === 'author' ? 'مؤلف كتب (وَرَق)' : 'معلم دورات (مَسار)' }}</h3>
                                    <p class="text-muted small mb-0">{{ \Illuminate\Support\Str::limit($app->experience, 100) }}</p>
                                </div>

                                @if($app->status === 'approved')
                                    <span class="status-pill status-pill--success">معتمد ومقبول</span>
                                @elseif($app->status === 'rejected')
                                    <span class="status-pill status-pill--urgent">مرفوض</span>
                                @else
                                    <div class="d-flex gap-2">
                                        <form action="{{ route('admin.application.decision', $app->id) }}" method="POST">
                                            @csrf
                                            <input type="hidden" name="decision" value="approved">
                                            <button type="submit" class="button button--primary btn-sm" style="padding: 6px 12px; font-size: 11px;">
                                                <i class="fas fa-check"></i> اعتماد
                                            </button>
                                        </form>

                                        <form action="{{ route('admin.application.decision', $app->id) }}" method="POST">
                                            @csrf
                                            <input type="hidden" name="decision" value="rejected">
                                            <button type="submit" class="button button--ghost text-danger btn-sm" style="padding: 6px 12px; font-size: 11px;">
                                                <i class="fas fa-times"></i> رفض
                                            </button>
                                        </form>
                                    </div>
                                @endif
                            </article>
                        @endforeach
                    </div>
                @endif
            </div>

            <div class="workspace-summary">
                <small class="text-muted">أحدث المستخدمين</small>
                <strong>{{ $recentUsers->count() }}</strong>
                <p>مستخدمون انضموا للمنظومة مؤخراً.</p>

                @foreach($recentUsers as $u)
                    <div class="d-flex justify-content-between py-2 border-bottom" style="border-color: var(--border) !important;">
                        <span>{{ $u->name }}</span>
                        <b class="text-lavender">#{{ $u->id }}</b>
                    </div>
                @endforeach
            </div>
        </div>
    </div>
</main>
@endsection