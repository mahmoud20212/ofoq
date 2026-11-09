<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>@yield('title', 'لوحة التحكم — ' . config('app.name'))</title>
    <link rel="icon" href="{{ asset('images/waraq-logo.png') }}" type="image/png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Alexandria:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{{ asset('css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ asset('css/fontawesome-free-6.4.2-web/css/all.min.css') }}">
    <link rel="stylesheet" href="{{ asset('css/ofuq-waraq.css') }}">
    @yield('head')
    @stack('styles')
</head>

<body class="ofuq-theme">
    <main class="dashboard-page">
        <div class="dashboard-layout">
            
            <!-- Mobile Sidebar Overlay -->
            <div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>

            <!-- Figma Sidebar -->
            <aside class="dashboard-sidebar" id="dashboardSidebar">
                <div class="d-flex justify-content-between align-items-center mb-4 px-2">
                    <a href="{{ url('/') }}" class="brand" aria-label="أُفُق">
                        <img src="{{ asset('images/waraq-logo.png') }}" alt="أُفُق">
                        <span>أُفُق</span>
                    </a>
                    <!-- Close button for mobile -->
                    <button class="btn btn-sm text-white d-md-none" onclick="toggleSidebar()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>

                <nav aria-label="قائمة لوحة التحكم">
                    <a href="{{ route('homePage') }}" @class(['active' => request()->routeIs('homePage')])>
                        <i class="fas fa-th-large" style="font-size: 14px;"></i>
                        <span>نظرة عامة</span>
                    </a>
                    <a href="{{ route('user.myProducts') }}" @class(['active' => request()->routeIs('user.myProducts')])>
                        <i class="fas fa-graduation-cap" style="font-size: 14px;"></i>
                        <span>دوراتي</span>
                    </a>
                    <a href="{{ route('myLibrary.index') }}" @class(['active' => request()->routeIs('myLibrary.*')])>
                        <i class="fas fa-book" style="font-size: 14px;"></i>
                        <span>مكتبتي</span>
                    </a>
                    <a href="{{ route('favorites.index') }}" @class(['active' => request()->routeIs('favorites.*')])>
                        <i class="far fa-heart" style="font-size: 14px;"></i>
                        <span>المفضلة</span>
                    </a>
                    <a href="{{ route('profile.show') }}" @class(['active' => request()->routeIs('profile.*')])>
                        <i class="far fa-user" style="font-size: 14px;"></i>
                        <span>حسابي</span>
                    </a>
                </nav>

                <a href="{{ url('/') }}" class="back-home">
                    <i class="fas fa-arrow-right"></i>
                    <span>العودة للرئيسية</span>
                </a>
            </aside>

            <!-- Dashboard Main Container -->
            <section class="dashboard-main">
                <!-- Topbar with Date, Title & Profile Pill -->
                <div class="dashboard-top">
                    <div class="d-flex align-items-start gap-3">
                        <!-- Mobile Menu Toggle -->
                        <button class="btn btn-outline-light d-md-none mt-1" onclick="toggleSidebar()">
                            <i class="fas fa-bars"></i>
                        </button>
                        <div>
                            <span class="eyebrow">
                                @php
                                    $now = \Carbon\Carbon::now();
                                    $arabicDays = ['Sunday'=>'الأحد', 'Monday'=>'الإثنين', 'Tuesday'=>'الثلاثاء', 'Wednesday'=>'الأربعاء', 'Thursday'=>'الخميس', 'Friday'=>'الجمعة', 'Saturday'=>'السبت'];
                                    $arabicMonths = ['1'=>'يناير','2'=>'فبراير','3'=>'مارس','4'=>'أبريل','5'=>'مايو','6'=>'يونيو','7'=>'يوليو','8'=>'أغسطس','9'=>'سبتمبر','10'=>'أكتوبر','11'=>'نوفمبر','12'=>'ديسمبر'];
                                    $dayName = $arabicDays[$now->format('l')] ?? $now->format('l');
                                    $monthName = $arabicMonths[$now->format('n')] ?? $now->format('F');
                                    echo $dayName . '، ' . $now->format('j') . ' ' . $monthName;
                                @endphp
                            </span>
                            <h1 class="mt-1">@yield('dashboard_title', 'مكتبتي')</h1>
                            <p class="mb-0">@yield('dashboard_subtitle', 'كل تفاصيل رحلتك محفوظة ومنظمة في مكان واحد.')</p>
                        </div>
                    </div>

                    <div class="profile-wrap">
                        <!-- Bootstrap Dropdown -->
                        <div class="dropdown">
                            <button class="profile-button" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                                <span>{{ mb_substr(Auth::user()->name ?? 'ل', 0, 1) }}</span>
                                <div>
                                    <strong>{{ Auth::user()->name ?? 'ليان أحمد' }}</strong>
                                    <small>{{ Auth::user()->is_author ? 'مؤلف معتمد' : (Auth::user()->is_admin ? 'مدير المنظومة' : 'طالبة') }}</small>
                                </div>
                                <i class="fas fa-chevron-down ms-2" style="font-size: 11px;"></i>
                            </button>
                            
                            <ul class="dropdown-menu dropdown-menu-end shadow profile-menu" style="background: var(--surface); border: 1px solid var(--border-hover); border-radius: 14px;">
                                <li><a class="dropdown-item text-white py-2" href="{{ route('profile.show') }}"><i class="fas fa-id-card me-2 text-lavender"></i> الملف الشخصي</a></li>
                                <li><a class="dropdown-item text-white py-2" href="{{ route('account.roles') }}"><i class="fas fa-user-shield me-2 text-sky"></i> أدواري وصلاحياتي</a></li>
                                <li><a class="dropdown-item text-white py-2" href="{{ route('account.security') }}"><i class="fas fa-lock me-2 text-lavender"></i> الأمان والجلسات</a></li>
                                <li><hr class="dropdown-divider border-secondary"></li>
                                <li>
                                    <a class="dropdown-item text-danger py-2" href="{{ route('logout') }}" onclick="event.preventDefault(); document.getElementById('dash-logout-form').submit();">
                                        <i class="fas fa-sign-out-alt me-2"></i> تسجيل الخروج
                                    </a>
                                    <form id="dash-logout-form" action="{{ route('logout') }}" method="POST" class="d-none">
                                        @csrf
                                    </form>
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>

                <!-- Content Area -->
                <div class="dashboard-content-wrap">
                    @yield('content')
                </div>
            </section>
        </div>
    </main>

    @include('partials.ai-chatbot')
    <script src="{{ asset('js/bootstrap.bundle.min.js') }}"></script>
    <script>
        // Sidebar Toggle for Mobile
        function toggleSidebar() {
            const sidebar = document.getElementById('dashboardSidebar');
            const overlay = document.getElementById('sidebarOverlay');
            
            sidebar.classList.toggle('is-open');
            overlay.classList.toggle('is-visible');
        }
    </script>
    @stack('scripts')
</body>

</html>