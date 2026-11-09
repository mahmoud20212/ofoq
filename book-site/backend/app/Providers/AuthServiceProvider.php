<?php

namespace App\Providers;

use Illuminate\Foundation\Support\Providers\AuthServiceProvider as ServiceProvider;
use Illuminate\Support\Facades\Gate;

class AuthServiceProvider extends ServiceProvider
{
    /**
     * The model to policy mappings for the application.
     *
     * @var array<class-string, class-string>
     */
    protected $policies = [
        //
    ];

    /**
     * Register any authentication / authorization services.
     */
    public function boot(): void
    {
        // ✅ Gate للأدمن — يقدر يدخل لوحة الإدارة
        Gate::define('admin', function ($user) {
            return (bool) $user->is_admin;
        });

        // ✅ Gate للمشرف — الأدمن كمان مشرف تلقائياً
        Gate::define('moderator', function ($user) {
            return (bool) $user->is_admin || (bool) $user->is_moderator;
        });

        // ✅ Gate للمؤلف — الأدمن كمان مؤلف تلقائياً
        Gate::define('author', function ($user) {
            return (bool) $user->is_author || (bool) $user->is_admin;
        });

        // ✅ Gate للمعلم — الأدمن كمان معلم تلقائياً
        Gate::define('teacher', function ($user) {
            return (bool) $user->is_teacher || (bool) $user->is_admin;
        });
    }
}