@extends('layouts.dashboard')

@section('title', 'مكتبتي — ' . config('app.name'))
@section('dashboard_title', 'مكتبتي')
@section('dashboard_subtitle', 'كل تفاصيل رحلتك محفوظة ومنظمة في مكان واحد.')

@section('content')
@php
    $colors = ['violet', 'blue', 'lavender', 'deep'];
@endphp

<div class="dashboard-panel">
    <!-- Panel Header -->
    <div class="dashboard-panel__header">
        <div>
            <span class="eyebrow" style="color: var(--lavender); font-size: 11px; font-weight: 600; display: block; margin-bottom: 6px;">مكتبتك الشخصية</span>
            <h2 style="color: #fff; margin: 0; font-size: 24px; font-weight: 800;">تابع القراءة</h2>
        </div>
        <a href="{{ route('searchProducts.index') }}" class="button button--primary" style="padding: 10px 22px; font-size: 13px; border-radius: 999px; text-decoration: none; display: inline-flex; align-items: center; gap: 8px;">
            <span>اكتشف كتباً</span>
            <i class="fas fa-arrow-left"></i>
        </a>
    </div>

    @if(session()->has('message'))
        <div class="alert alert-success mt-3 mb-0" style="background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.3); color: #86efac; border-radius: 12px; font-size: 13px;">
            <i class="fas fa-check-circle me-1"></i>
            <span>{{ session()->get('message') }}</span>
        </div>
    @endif

    <!-- Library Grid -->
    @if(isset($books) && count($books) > 0)
        <div class="dashboard-library">
            @foreach($books as $index => $book)
                @php $color = $colors[$index % 4]; @endphp
                <article>
                    <a href="{{ url('/products/' . $book->slug) }}" class="book book--{{ $color }}">
                        <span class="book__mark">
                            <img src="{{ asset('images/waraq-logo.png') }}" alt="أُفُق">
                        </span>
                        <small>{{ $book->category ?? 'عام' }}</small>
                        <strong>{{ $book->name }}</strong>
                        <em>مؤلف معتمد</em>
                    </a>
                    <div>
                        <span>{{ $book->progress ?? 0 }}٪ مقروء</span>
                        <a href="{{ url('/read/' . $book->slug) }}">
                            <span>متابعة القراءة</span>
                            <i class="fas fa-arrow-left"></i>
                        </a>
                    </div>
                </article>
            @endforeach
        </div>
    @else
        <!-- Empty State -->
        <div class="text-center py-5 my-4 glass-card" style="border-radius: 20px; border: 1px solid var(--border);">
            <i class="fas fa-book-open fa-3x mb-3" style="color: var(--lavender) !important; opacity: 0.6;"></i>
            <h4 class="text-white fw-bold mb-2">مكتبتك فارغة حالياً</h4>
            <p class="text-muted small mb-4">لم تقم بإضافة أي كتب لمكتبتك بعد. تصفح المكتبة واختر كتابك الأول!</p>
            <a href="{{ route('searchProducts.index') }}" class="button button--primary">
                <i class="fas fa-search"></i> تصفح الكتب الآن
            </a>
        </div>
    @endif
</div>
@endsection