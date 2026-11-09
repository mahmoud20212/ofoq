<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use App\Models\EmergencyRequest;
use App\Notifications\EmergencyNotification;
use App\Models\User;
use Illuminate\Support\Facades\Notification; // ✅ إضافة

class EmergencyRequestsController extends Controller
{
    public function index()
    {
        return view('emergancyRequest.index')
            ->with('emergancyRequest', EmergencyRequest::orderBy('created_at', 'DESC')->get());
    }

    public function create()
    {
        return view('emergancyRequest.create');
    }

    public function store(Request $request)
    {
        // التحقق من صحة البيانات المدخلة
        $request->validate(
            [
                'description' => 'required',
                'location' => 'required',
                'whatsapp' => ['required', 'regex:/^[0-9\s\-\+]+$/'],
            ],
            [
                'whatsapp.regex' => 'يرجى إدخال رقم واتساب صالح .',
            ]
        );

        // إنشاء الطلب الطارئ
        $emergencyRequest = EmergencyRequest::create([
            'type' => null,
            'description' => $request->input('description'),
            'location' => $request->input('location'),
            'whatsapp' => $request->input('whatsapp'),
            'user_id' => auth()->user()->id
        ]);

        // ✅ تحسين: إرسال إشعارات للمستخدمين الآخرين فقط (استبعاد صاحب الطلب)
        $users = User::where('id', '!=', auth()->id())->get();
        
        // ✅ استخدام Notification::send بدل اللوب (أسرع للذاكرة)
        Notification::send($users, new EmergencyNotification($emergencyRequest));

        return redirect('/emergancyRequest')->with('message', 'تم إضافة الطلب الطارىء بنجاح!');
    }

    public function show($id)
    {
        return view('emergancyRequest.show')
            ->with('emergencyRequest', EmergencyRequest::where('id', $id)->first());
    }

    public function edit($id)
    {
        $emergencyRequest = EmergencyRequest::findOrFail($id);

        // ✅ Ownership check — صاحب الطلب أو أدمن
        if (auth()->id() !== $emergencyRequest->user_id && !auth()->user()->is_admin) {
            abort(403, 'ليس لديك صلاحية لتعديل هذا الطلب');
        }

        return view('emergancyRequest.edit')
            ->with('emergancyRequest', $emergencyRequest);
    }

    public function update(Request $request, string $id)
    {
        $emergencyRequest = EmergencyRequest::findOrFail($id);

        // ✅ Ownership check — صاحب الطلب أو أدمن
        if (auth()->id() !== $emergencyRequest->user_id && !auth()->user()->is_admin) {
            abort(403, 'ليس لديك صلاحية لتعديل هذا الطلب');
        }

        // التحقق من صحة البيانات المدخلة
        $request->validate(
            [
                'description' => 'required',
                'location' => 'required',
                'whatsapp' => ['required', 'regex:/^[0-9\s\-\+]+$/'],
            ],
            [
                'whatsapp.regex' => 'يرجى إدخال رقم واتساب صالح .',
            ]
        );

        // تحديث الطلب (بدون تغيير user_id — صاحب الطلب الأصلي يبقى)
        $emergencyRequest->update([
            'description' => $request->input('description'),
            'location' => $request->input('location'),
            'whatsapp' => $request->input('whatsapp'),
        ]);

        return redirect('/emergancyRequest/' . $id)
            ->with('message', 'تم تعديل الطلب بنجاح');
    }

    public function destroy(string $id)
    {
        $emergencyRequest = EmergencyRequest::findOrFail($id);

        // ✅ Ownership check — صاحب الطلب أو أدمن
        if (auth()->id() !== $emergencyRequest->user_id && !auth()->user()->is_admin) {
            abort(403, 'ليس لديك صلاحية لحذف هذا الطلب');
        }

        $emergencyRequest->delete();

        return redirect('/emergancyRequest')
            ->with('message', 'تم حذف الطلب بنجاح');
    }
}