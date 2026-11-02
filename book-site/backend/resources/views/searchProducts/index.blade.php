@extends('layouts.app')
@section('title', 'نتائج البحث')

@section('content')
<div class="search-results-page main-content">
    <form action="/searchProducts" method="get">
        <div class="search-bar">
            <input type="text" name="search" value="{{ Request::get('search') }}" placeholder="ابحث هنا...">
            <i class="fas fa-search"></i>
        </div>
    </form>

    <div class="container px-3 pb-4">
        <section class="search-results-section search-results-section--books" aria-labelledby="search-books-title">
            <h2 id="search-books-title">
                نتائج البحث عن "{{ Request::get('search') }}" في الكتب
                <i class="fas fa-book"></i>
            </h2>

            @if($products->isEmpty())
                <p class="search-results-empty text-center"><strong>لا يوجد نتائج</strong></p>
            @else
                <div class="row g-4">
                    @foreach($products as $product)
                        <div class="col-sm-6 col-lg-4">
                            <div class="card h-100 text-center">
                                @if($product->image_path)
                                    <img src="{{ asset('images/' . $product->image_path) }}" class="card-img-top" alt="{{ $product->name }}">
                                @else
                                    <img src="https://via.placeholder.com/300" class="card-img-top" alt="صورة افتراضية">
                                @endif
                                <div class="card-body">
                                    <h5 class="card-title">اسم الكتاب: {{ $product->name }}</h5>
                                    <p class="card-text">وصف الكتاب: {{ $product->description }}</p>
                                    <a href="/products/{{ $product->slug }}" class="btn btn-primary">عرض التفاصيل</a>
                                </div>
                            </div>
                        </div>
                    @endforeach
                </div>
            @endif
        </section>

        <section class="search-results-section search-results-section--urgent" aria-labelledby="search-urgent-title">
            <h2 id="search-urgent-title" class="text-danger">
                نتائج البحث عن "{{ Request::get('search') }}" في الطلبات العاجلة
                <i class="fas fa-exclamation-triangle"></i>
            </h2>

            @if($emergencyRequest->isEmpty())
                <p class="search-results-empty text-center"><strong>لا يوجد نتائج</strong></p>
            @else
                <div class="row g-4">
                    @foreach($emergencyRequest as $request)
                        <div class="col-sm-6 col-lg-4">
                            <div class="card h-100 text-center">
                                <div class="urgent-appeal-card__media">
                                    @include('partials.urgent-request-visual')
                                </div>
                                <div class="card-body">
                                    <h5 class="card-title">{{ \Illuminate\Support\Str::limit($request->description, 65) }}</h5>
                                    <p class="small text-muted">عرض التفاصيل</p>
                                    <a href="/emergancyRequest/{{ $request->id }}" class="btn urgent-card-cta">عرض التفاصيل</a>
                                </div>
                            </div>
                        </div>
                    @endforeach
                </div>
            @endif
        </section>

        <div class="text-center search-results-page__footer">
            <a href="{{ route('homePage') }}" class="home-btn">
                <span>العودة للصفحة الرئيسية</span>
                <i class="fas fa-arrow-left" aria-hidden="true"></i>
            </a>
        </div>
    </div>
</div>
@endsection
