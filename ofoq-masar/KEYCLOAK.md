# مركز حسابات أُفُق ومَسار

## التشغيل المحلي
- المركز: http://localhost:8081/realms/ofoq-dev
- الأكاديمية: http://localhost:8000 — العميل: ofoq-masar
- بداية الدخول من 127.0.0.1 تحول إلى localhost، وتنقل معرّفات سلة الزائر بتوقيع محدود الصلاحية.
- تثبيت المكتبات: `uv sync`، ثم من educa شغّل `uv run python manage.py migrate` و`uv run python manage.py runserver`.
- تشغيل المركز: `docker start ofoq-keycloak-dev`.
- إعداد العميل المحلي: `node scripts/setup-keycloak.mjs` من جذر المشروع. الأسرار محفوظة في .env.local المستثنى من Git؛ لا تغييرات على الثيم أو العملاء الآخرين.
- احتفظ بـ DJANGO_SECRET_KEY ثابتًا؛ تغييره يبطل الجلسات القديمة.

## الروابط
- /auth/login/ و/auth/register/ لبدء الدخول والتسجيل المركزيين.
- /auth/callback/ عنوان الرجوع المسجل في العميل.
- /auth/account/ للانتقال إلى مركز الحسابات.
- /auth/logout/ يقبل POST مع CSRF وينهي الجلسة المحلية ثم المركزية.
- /auth/backchannel-logout/ يتحقق من رسالة خروج موقّعة قبل إبطال الجلسات.
- عنوان الخروج من داخل Docker: http://host.docker.internal:8000/auth/backchannel-logout/، واسم المضيف مسموح في وضع التطوير فقط.

## ربط الحسابات القديمة
لا دمج بالبريد. الهوية باستخدام issuer + sub، ولا منح لصلاحيات الإدارة تلقائيًا.
للربط الإداري الصريح قبل أول دخول:
`uv run python manage.py link_keycloak_user --user-id USER_ID --subject KEYCLOAK_SUB --confirm`
الأمر يرفض الارتباطات المتعارضة ويحافظ على الدورات والصلاحيات. إذا دخلت الهوية سابقًا وأنشأت مستخدمًا محليًا، يلزم تدقيق إداري بدل دمج تلقائي.
دخول /admin/login/ المحلي محفوظ للإدارة الحالية.

## الجلسات والتحقق
الرموز مشفرة في الخادم؛ ملف ارتباط masar_session يحتوي معرّف جلسة فقط. التجديد عند الحاجة، والخروج المركزي يبطل الجلسات بإشعار موقّع. انتهاء جلسة المركز يؤثر عند التجديد إن لم يصل إشعار.
الخروج من المنصات الأخرى يعتمد على دعمها للخروج المركزي؛ لم تتغير ضمن هذا العمل.
اختبارات معزولة: `uv run python manage.py test courses.tests_sso courses.tests_catalogue courses.tests_details`.
الالتحاق والدفع والتقييمات ما زالت مؤجّلة.

## النشر
اضبط MASAR_AUTH_URL وKEYCLOAK_ISSUER وKEYCLOAK_CLIENT_ID وKEYCLOAK_CLIENT_SECRET وDJANGO_SECRET_KEY. يلزم HTTPS عند DEBUG=False، وALLOWED_HOSTS وعناوين الرجوع والخروج الصحيحة. سكربت الإعداد محلي فقط.
