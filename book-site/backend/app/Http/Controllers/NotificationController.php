<?php

namespace App\Http\Controllers;

use Illuminate\Support\Facades\Auth;
use App\Models\EmergencyRequest;

class NotificationController extends Controller
{
    public function index()
    {
        // ✅ تحسين: جلب الإشعارات غير المقروءة فقط
        $notifications = auth()->user()->unreadNotifications;

        return view('notification.index', compact('notifications'));
    }

    public function showAndMarkAsRead($notificationId)
    {
        // ✅ تحسين: query builder بدل تحميل الكل في الذاكرة
        $notification = auth()->user()->notifications()->find($notificationId);

        if (!$notification) {
            return redirect()->route('notification.index')->with('error', 'الإشعار غير موجود.');
        }

        // تحديث الإشعار إلى مقروء
        $notification->markAsRead();

        // جلب الطلب المرتبط بالإشعار
        $emergencyRequest = EmergencyRequest::find($notification->data['emergency_request_id'] ?? null);

        // التأكد من أن الطلب ما زال موجودًا
        if (!$emergencyRequest) {
            return redirect()->route('notification.index')->with('error', 'عذرًا، الطلب المرتبط بهذا الإشعار قد تم حذفه.');
        }

        // عرض الطلب
        return view('emergancyRequest.show', compact('emergencyRequest'));
    }

    public function destroy($id)
    {
        // ✅ تحسين: query builder + null check
        $notification = Auth::user()->notifications()->find($id);

        // إذا لم يتم العثور على الإشعار (مثلاً تم حذفه مسبقاً)
        if (!$notification) {
            return redirect()->route('notification.index')->with('error', 'الإشعار غير موجود أو تم حذفه مسبقاً.');
        }

        // حذف الإشعار
        $notification->delete();

        // إعادة التوجيه بعد الحذف
        return redirect()->route('notification.index')->with('success', 'تم حذف الإشعار بنجاح');
    }

    public function clear()
    {
        $user = Auth::user();

        // ✅ تحسين: حذف مباشر بـ query builder بدل تحميل الكل (أسرع وأخف)
        $user->notifications()->delete();

        return back()->with('success', 'تم حذف جميع الإشعارات بنجاح.');
    }
}