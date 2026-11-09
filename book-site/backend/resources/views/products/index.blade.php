@extends('layouts.app')
@section('title', 'الكتب المتاحة للتبرع — ' . config('app.name'))

@section('content')
@php
    $totalCount = $products->count();
    $colors = ['violet', 'blue', 'lavender', 'deep'];
@endphp
<div class="catalog-page">
    <div class="glow glow--one" aria-hidden="true"></div>
    <div class="glow glow--two" aria-hidden="true"></div>
    <div class="grid-bg" aria-hidden="true"></div>

    <div class="container-ofuq position-relative" style="z-index: 5;">
        <!-- Header -->
        <div class="catalog-header text-center">
            <div class="platform-pill mx-auto mb-3" style="width: fit-content;">
                <i class="fas fa-book-open text-lavender"></i>
                <span>كتب ومراجع</span>
            </div>
            <h1 class="catalog-title">الكتب المتاحة للتبرع</h1>
            @if($totalCount > 0)
            <p class="text-muted fs-6"><span class="text-white fw-bold">{{ $totalCount }}</span> {{ $totalCount > 1 ? 'كتب' : 'كتاب' }} في المنصة</p>
            @endif
        </div>

        @if(session()->has('message'))
        <div class="alert alert-success d-flex align-items-center gap-2 mx-auto mb-4" style="max-width: 600px; background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.3); color: #86efac; border-radius: 14px;">
            <i class="fas fa-check-circle"></i>
            <span>{{ session()->get('message') }}</span>
        </div>
        @endif

        @if($totalCount === 0)
        <!-- Empty State -->
        <div class="text-center py-5 glass-card mx-auto" style="max-width: 600px; border-radius: 24px;">
            <i class="fas fa-box-open fa-4x text-muted mb-3" style="color: var(--lavender) !important; opacity: 0.5;"></i>
            <h4 class="text-white fw-bold mb-2">لا توجد كتب مضافة بعد</h4>
            <p class="text-muted small mb-4">عندما يضيف الأعضاء كتبهم ومراجعهم ستظهر هنا.</p>
            @auth
            <a href="{{ url('/products/create') }}" class="button button--primary">
                <i class="fas fa-plus"></i> إضافة كتاب
            </a>
            @endauth
        </div>
        @else
        <!-- 3D Books Grid -->
        <div class="catalogue-books mt-5">
            @foreach($products as $index => $product)
                @php $color = $colors[$index % 4]; @endphp
                <article>
                    <a href="{{ url('/products/' . $product->slug) }}" class="book book--{{ $color }}">
                        <span class="book__mark">
                            <img src="{{ asset('images/waraq-logo.png') }}" alt="أُفُق">
                        </span>
                        <small>{{ $product->category ?? 'عام' }}</small>
                        <strong>{{ $product->name }}</strong>
                        <i></i>
                        <em>{{ $product->user->name ?? 'مؤلف معتمد' }}</em>
                    </a>
                </article>
            @endforeach
        </div>
        @endif

        <div class="text-center mt-5">
            <a href="{{ route('homePage') }}" class="button button--secondary">
                <span>العودة للصفحة الرئيسية</span> <i class="fas fa-arrow-left"></i>
            </a>
        </div>
    </div>
</div>
@endsection