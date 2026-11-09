<?php

namespace App\Notifications;

use App\Models\EmergencyRequest;
use Illuminate\Bus\Queueable;
use Illuminate\Contracts\Queue\ShouldQueue; // ✅ إضافة
use Illuminate\Notifications\Messages\MailMessage;
use Illuminate\Notifications\Notification;

class EmergencyNotification extends Notification implements ShouldQueue // ✅ implements
{
    use Queueable;

    protected $emergencyRequest;

    public function __construct(EmergencyRequest $emergencyRequest)
    {
        $this->emergencyRequest = $emergencyRequest;
    }

    public function via($notifiable)
    {
        return ['database']; // أو mail حسب الطريقة اللي تفضلها
    }

    public function toArray($notifiable)
    {
        return [
            'title' => 'طلب عاجل جديد',
            'type' => $this->emergencyRequest->type,
            'description' => $this->emergencyRequest->description,
            'location' => $this->emergencyRequest->location,
            'whatsapp' => $this->emergencyRequest->whatsapp,
            'link' => "/emergancyRequest/{$this->emergencyRequest->id}",
            'emergency_request_id' => $this->emergencyRequest->id,
        ];
    }
}