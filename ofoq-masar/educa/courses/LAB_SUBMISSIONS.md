# «تحقق من الحل» — خدمات ومسارات وعامل فقط

حفظ مسودة كود الطالب وسجل المحاولات وقراءة لقطة الكود موثقة في [LAB_EDITOR.md](LAB_EDITOR.md).

## التنفيذ والملفات

نعيد استخدام Judge0Client وLabRunQueueControl وأوامر العامل الحالي، دون اعتماديات أو broker
جديد أو تنفيذ كود داخل Django. المحاولة هي `ChallengeSubmission`؛ الحالة النهائية لكل اختبار
هي `SubmissionTestResult`، والإنجاز الدائم هو `ChallengeSuccess`.

- جديدان: `lab_submission_services.py` و`lab_submission_views.py` داخل courses.
- ترحيل إضافي `0022_lab_submission_queue.py`، واختبارات `tests_lab_submissions.py` وهذه الوثيقة.
- تحديث `lab_models.py` و`lab_run_services.py` و`lab_run_views.py` والعامل
  `management/commands/lab_run_worker.py`، و`educa/urls.py` وإعدادات التطبيق والمعاينة.
- تحديث LAB.md وLAB_RUNS.md وLAB_JUDGE0.md. تقارير التحقق الفعلي وسكربتاته في
  `deploy/judge0/.local/` المستثناة من Git، ولا تحوي مفاتيح اتصال ضمن مخرجاتها العامة.

`LAB_SUBMISSION_API_ENABLED=False` و`LAB_SUBMISSION_WORKER_ENABLED=False` افتراضيًا؛
تُفعلان في `educa.judge0_preview_settings` فقط. لا واجهات طالب/معلّم أو قبول إنتاج هنا.
لم يتغير تقدم المحتوى أو الاستئناف أو استحقاق الشهادات. `LabRun` لا يسجل «تم الحل».

## قبول الطلب

`POST /lab/challenges/<challenge_id>/submissions/`

جلسة نشطة وCSRF، مع `Content-Type: application/json` وcookie `masar_csrf` وترويسة X-CSRFToken.

```json
{
  "request_id": "cb61dbd2-c18b-41cd-9b9c-2c79bd346d63",
  "code": "a,b=map(int,input().split()); print(a+b)"
}
```

هذه هي الحقول المقبولة فقط؛ لا stdin أو example_id أو اختبار/لغة/موارد/هوية طالب من المتصفح.
اللغة والإصدار والحدود والمقارنة والحالات وإعدادات إظهارها تؤخذ من النسخة المنشورة بعد تحقق
challenge_for_execution الحالي، بما فيه التحاق الدورة. لا دخول لمسودة أو معاينة معلّم.

يرد 202 سريعًا بمعرّف المحاولة دون اتصال Judge0، وLocation وstatus_url:

```json
{
  "submission_id": 1,
  "request_id": "cb61dbd2-c18b-41cd-9b9c-2c79bd346d63",
  "version_uid": "UUID النسخة المثبتة",
  "status": "queued",
  "phase": "queued",
  "passed": null,
  "created": true,
  "status_url": "/lab/submissions/1/"
}
```

يبقى إيصال POST مختصرًا بصرف النظر عن عدد/حجم الحالات؛ التفاصيل عبر GET الموثّق.
نفس المفتاح والبيانات للطالب نفسه يعيدان 200 بالسجل ذاته وcreated=false؛ اختلاف الكود أو
التحدي مع المفتاح نفسه يعيد 409. المفتاح مستقل بين طالبين، ومستقل بين «تشغيل» و«تحقق».
لا تعاد المحاولة أو الحالة البعيدة لمجرد تكرار HTTP أو إغلاق الصفحة.

المساران يشتركان في حدود LAB_RUN_LIMITS وقفل القبول: اثنتان نشطتان للطالب و16 إجمالًا،
و10 طلبات مقبولة لكل طالب في 60 ثانية، عبر النوعين معًا. حالات uncertain تحتفظ بحصتها.
حد المصدر 100000 محرف و400000 بايت، وجسم JSON 600000 بايت، مع حدود الاتصال الأصغر.
تُرفض الحقول والمفاتيح المكررة والمدخلات غير الصالحة. الحالات حتى 200 افتراضيًا، وفق
LAB_REFERENCE_MAX_CASES، ولكل stdin سقف خدمة الاتصال. لا تُقص بيانات التقييم بصمت.

## الحالة والنتيجة والخصوصية

`GET /lab/submissions/<submission_id>/`

الصاحب النشط فقط؛ مستخدم آخر 404 وانتهاء الجلسة 401. يُراجع استحقاق الدورة عند كل قراءة.
الدورات المؤرشفة تبقى للملتحق. أرشفة التحدي تمنع قبول محاولات جديدة، ولا تمحو المقبولة سابقًا.
إعادة النشر لا تمنع قراءة المحاولة القديمة المسموحة أو تعيد تفسيرها؛ version_uid يوضح نسختها.
للبيانات السابقة قبل FK التاريخ، تُستعاد هوية التحدي من اللقطة غير القابلة للتعديل دون تحديثها.
حذف هوية المصدر إداريًا يفشل الوصول مغلقًا إذا تعذر تحقق الاستحقاق، مع بقاء السجل للإدارة.

مثال مختصر لفشل محاولة مع بقاء إنجاز سابق لنفس النسخة:

```json
{
  "submission_id": 2,
  "version_uid": "UUID النسخة المثبتة",
  "status": "finished",
  "phase": "complete",
  "terminal": true,
  "verdict": "wrong_answer",
  "passed": false,
  "solved": true,
  "needs_operator_review": false,
  "error_code": null,
  "error_message": null,
  "language": {"name": "Python", "version": "3.8.1"},
  "total_cases": 2,
  "evaluated_cases": 2,
  "visible_results": [{
    "case_id": "UUID الحالة الظاهرة",
    "order": 0,
    "stdin": "2 3\n",
    "expected_output": "5\n",
    "verdict": "accepted",
    "stdout": "5\n",
    "stderr": "",
    "compile_output": ""
  }],
  "hidden_summary": {"total": 1, "evaluated": 1, "passed": 0, "not_passed": 1}
}
```

يُضاف request_id وcreated_at وfinished_at. passed يصف **هذه المحاولة** (null قبل النهاية)،
وsolved يصف وجود إنجاز سابق لهذه النسخة بالذات؛ لا تعارض بين passed=false وsolved=true.
لا تنتقل علامة solved تلقائيًا إلى نسخة تحدٍّ جديدة.

الحالات الظاهرة فقط تعرض stdin/expected/stdout/stderr/compile_output؛ المخرجات محدودة
البايتات وتُعرض لاحقًا كنص escaped/textContent، لا HTML. خطأ خدمة في حالة ظاهرة يحجب نصها
التقني أيضًا. المخفية تعرض أعدادًا فقط: لا ID أو ترتيب أو مدخل أو متوقع أو فعلي أو خطأ/ترجمة
أو token أو وقت/ذاكرة خاصين بحالة مخفية. لا حقول خاصة مخفية مجمّعة في الجذر.
الظهور ثابت من اللقطة لا من جدول مصدر قد تغيّر لاحقًا. الردود private,no-store.

queued/running/finished/failed حالات المحاولة؛ phase يوضح queued/dispatching/submitted/
uncertain/complete/error. verdict يميز wrong_answer عن compile_error/runtime_error/
time_limit/memory_limit/output_limit وعن system_error. رسائل الأخطاء ثابتة وآمنة ولا تتضمن
جسم upstream أو سياق الحالة المخفية. أي فشل خدمة يمنع النجاح، ويكون status=failed
وverdict=system_error، لا إجابة خاطئة. قبل اكتمال كل الحالات تبقى passed=null.

## العامل وتسجيل الإنجاز

لقطة `purpose=submission` تحفظ الكود والنسخة واللغة والحدود وسياسة المقارنة وحالات الاختبار
مرتبة بمدخلاتها ومتوقعاتها وظهورها. لا حاجة لنسخ الحل المرجعي إلى محاولة الطالب.
بقي توافق اللقطات القديمة محفوظًا. الحذف الإداري للمصدر لا يمحو نتائج المحاولات السابقة.

`private_result.case_states` دفتر تسليم خاص على الخادم، مفهرس بـUUID الحالة، يحتوي phase
وtoken وsubmitted_at وحالة المتابعة. لا نموذج نتائج موازٍ: الجدول SubmissionTestResult هو
النتيجة النهائية لكل حالة. يحفظ token فور استلامه وقبل GET؛ ويثبت dispatching قبل POST.
lease ومقارنة UUID ملكيته تمنع عاملًا قديمًا من الكتابة فوق عامل جديد.

ينفذ العامل خطوة محدودة لحالة واحدة، ثم يحرر lease أو يؤجل الاستعلام. عند اكتمالها يطابق
stdout محليًا باستخدام compare_outputs الموجودة (exact أو توحيد CRLF/CR إلى LF فقط، دون trim).
expected_output لا يُرسل إلى Judge0، ولا يعتمد الحكم على حالة accepted البعيدة وحدها.
لا short-circuit لمجرد جواب خاطئ: تستمر بقية الحالات ضمن اللقطة. لا توجد حالة مراجعة معلّم لحل الطالب.

حفظ نتيجة المحاولة النهائية وChallengeSuccess يتم في **معاملة واحدة**، مع قفل مشترك وقيد
تفرد student+version_uid؛ فشل كتابة الإنجاز يرجع نهائية المحاولة. تبقى نتائج الحالات المحفوظة
للاستعادة، فلا يعاد تنفيذها عند إعادة محاولة المعاملة. إعادة النجاح تحفظ سجل الإنجاز الأول
وتاريخه ورابطه، وفشل محاولة لاحقة لا يحذفه أو يستبدله. «تم الحل» من هذا التقييم فقط.

## تشغيل العامل وإيقافه والاستعادة

من educa باستخدام البيئة الحالية، تشغيل التقييم فقط:

```text
..\.venv\Scripts\python.exe -B manage.py lab_run_worker --settings=educa.judge0_preview_settings --kind submission
```

العامل المشترك افتراضيًا --kind all بالتناوب بين النوعين؛ ويمكن --kind run للحفاظ على تشغيل
التجارب وحده. خطوة محدودة/تشخيص محاولة بعينها:

```text
..\.venv\Scripts\python.exe -B manage.py lab_run_worker --settings=educa.judge0_preview_settings --once --limit 1 --submission-id 1
```

--once لا يعني انتظار نهاية كل الحالات. Ctrl+C/SIGTERM يوقف بعد الخطوة المحدودة، ولا يلزم
إيقاف Judge0 أو SSH. قتل العملية المفاجئ يترك lease للاستعادة الآمنة بعد انتهائها.
لم يُترك عامل دائم أو خادم معاينة يعمل بعد التحقق.

- token محفوظ: العملية الجديدة GET فقط للحالة، ولو تغير المنشور أو أُغلقت الصفحة.
- انتهاء lease بعد dispatching بلا token: uncertain، دون POST تلقائي. تبقى الحصة محجوزة
  لحين تسوية احتمال قبول العملية؛ لا وعد exactly-once بعد فقد رد الإرسال الأول.
- فشل GET: يُحفظ token ويتراجع الاستعلام 2–16 ثانية. بعد 1800 ثانية انتظار/انقطاع تحتاج
  الحالة مراجعة بدل الاستعلام بلا حد أو اختراع نتيجة.
- pause المشتركة توقف القبول والإرسال الجديد؛ تستمر متابعة token الموجود، ثم تنتظر الحالة
  التالية الاستئناف. المحاولات المقبولة قبل الأرشفة تستمر بلقطتها؛ فقد الوصول يمنع أول إرسال
  غير مبدوء والقراءة، ولا تُكشف نتائج عملية بعيدة بدأت لمن فقد استحقاقه.

```text
..\.venv\Scripts\python.exe -B manage.py lab_run_worker --settings=educa.judge0_preview_settings --pause
..\.venv\Scripts\python.exe -B manage.py lab_run_worker --settings=educa.judge0_preview_settings --resume
..\.venv\Scripts\python.exe -B manage.py lab_run_worker --settings=educa.judge0_preview_settings --retry-submission-poll ID
..\.venv\Scripts\python.exe -B manage.py lab_run_worker --settings=educa.judge0_preview_settings --abandon-submission ID --reason "سبب التسوية بعد مراجعة المهمة البعيدة"
```

إجراءات المشغّل للمضيف الموثوق، لا HTTP للطلاب. retry لا يعمل دون token معلوم للحالة
غير المكتملة، ويستأنف GET فقط. abandon يسجل السبب وفشل خدمة ويفرغ الحصة، بعد تسوية
احتمال استمرار المهمة البعيدة، ولا يحذف الإنجاز السابق. لا إعادة إرسال ضمن هذه الإجراءات.

## التحقق المنفصل عن بيانات المشروع

### المحاكاة والقيود

**134 اختبارًا ناجحًا، صفر فشل وصفر تخطٍ** في:
`courses.tests_lab_submissions` (28) و`courses.tests_lab_runs` و`courses.tests_judge0`
و`courses.tests_lab_services` و`courses.tests_lab_models`.
SQLite بالذاكرة وملفات مؤقتة وكاش/قنوات/بريد معزولة. Django check سليم، و
`makemigrations courses students --check --dry-run` لا يقترح تغييرات.

شملت: كل الحالات، مخفية خاطئة/مهلة/فشل خدمة ومنع التسريب، CSRF والملكية والالتحاق
والأرشفة والمسودات، idempotency والتعارض والحصص المشتركة، تعطل العامل بعد حفظ token،
إرسال مجهول، مهلة المتابعة والاستئناف، سياسة المقارنة، ثبات النتيجة عند تغيير المنشور،
والتراجع الذري عند فشل الإنجاز. ثلاثة اختبارات تزامن جديدة (عاملان لنفس الحالة، قبول مكرر،
ومحاولتان ناجحتان للإنجاز نفسه)، وستة مع اختبارات التشغيل. لا اختبار PostgreSQL أو حمل إنتاج.
Judge0 في هذه المجموعة محاكى؛ لا توصف بأنها تجربة خدمة فعلية.

### تجربة AWS الفعلية

استخدمت Python 3.8.1 والتحدي الاصطناعي المعتمد في المعاينة، دون إعادة اختبارات اللغات أو
الفحص المرجعي السابقين. HTTP حقيقي على loopback وجلسة طالب اصطناعي وCSRF، وعامل CLI
بعملية Python جديدة لكل خطوة، مع النفق وخدمة AWS الحاليين دون تغييرهما:

| التجربة | الظاهرة | ملخص المخفية | المحاولة | الإنجاز |
| --- | --- | --- | --- | --- |
| جمع صحيح | accepted وناتج 5 | واحدة مجتازة | passed=true | سجل واحد |
| استخدام abs(a)+b | accepted وناتج 5 | واحدة لم تجتز | wrong_answer وpassed=false | بقي السجل الأول |

القبول 202 خلال نحو 380ms ثم 90ms في هاتين العينتين. المكرر أعاد السجل نفسه، وتغيير
الكود بالمفتاح نفسه أعاد 409. تتبع HTTP أثبت **4 POST لأربع حالات فقط**؛ لكل token
استعلام من عملية عامل جديدة، دون إعادة إرسال حالته. استجابة الطالب تضم حالة ظاهرة واحدة
وملخصًا عدديًا فقط للمخفية، ولا UID أو مدخلات أو مخرجات أو أخطاء مخفية. طالب آخر حصل على 404.
قياسات العينتين لا تثبت سعة إنتاج أو ضمان زمن استجابة.

التقرير: `deploy/judge0/.local/submission-queue-e2e-2026-11-19-results.json` والتتبع بجانبه.
أُوقف خادم HTTP التجريبي وانتهت عمليات العامل، وحُذفت الجلسات التجريبية، وبقيت المحاولات
والنتائج للمراجعة داخل المعاينة. بصمة قاعدة المشروع الفعلية متطابقة قبل/بعد، والترحيل 0022
طُبق على المعاينة فقط. لا نشر إنتاج أو تغيير Keycloak أو اعتماديات أو تشغيل عام للطلاب.

الواجهات والقبول العام وسياسات الإنتاج والمراقبة وحمل العمل الموزع والتدقيق الأمني الشامل
خارج هذه المهمة؛ نجاح التقييم هنا لا يساوي شهادة أو اجتيازًا للدورة التعليمية.
