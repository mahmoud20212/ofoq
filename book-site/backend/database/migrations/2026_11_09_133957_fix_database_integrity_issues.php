<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        // 1. إصلاح نوع البيانات لعمود last_page في جدول user_books
        if (Schema::hasColumn('user_books', 'last_page')) {
            Schema::table('user_books', function (Blueprint $table) {
                // تحويل النص إلى رقم صحيح (integer)
                $table->integer('last_page')->nullable()->change();
            });
        }

        // 2. حذف عمود is_read المكرر من جدول notifications
        if (Schema::hasColumn('notifications', 'is_read')) {
            Schema::table('notifications', function (Blueprint $table) {
                $table->dropColumn('is_read');
            });
        }

        // 3. حذف جدول categories الميت (غير المستخدم)
        Schema::dropIfExists('categories');
    }

    public function down(): void
    {
        // التراجع عن التعديلات في حالة الرغبة في الـ Rollback
        Schema::table('user_books', function (Blueprint $table) {
            $table->text('last_page')->nullable()->change();
        });

        Schema::table('notifications', function (Blueprint $table) {
            $table->boolean('is_read')->default(false);
        });

        // إعادة إنشاء جدول categories (في حالة التراجع)
        Schema::create('categories', function (Blueprint $table) {
            $table->id();
            $table->string('name')->unique();
            $table->string('slug')->unique();
            $table->text('description')->nullable();
            $table->string('icon')->nullable();
            $table->unsignedBigInteger('parent_id')->nullable();
            $table->integer('order')->default(0);
            $table->timestamps();
            $table->foreign('parent_id')->references('id')->on('categories')->onDelete('cascade');
        });
    }
};