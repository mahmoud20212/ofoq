# تحليل ERD — منصة أُفق ورق

> **الغرض**: تحويل تحليل منصة «ورق» إلى مخطط علاقات كيانات (ERD) قابل للتنفيذ على Laravel.
> **الحالة**: مسودة معتمدة للتصميم — تحتاج حسم القرارات المفتوحة (قسم 6) قبل التنفيذ النهائي.
> **آخر تحديث**: 2026-11-05
> **المرجع**: `ANALYSIS.html`

---

## 1. نظرة عامة

| البند | القيمة |
|---|---|
| عدد الكيانات | 27 جدولًا |
| عدد النطاقات | 7 |
| نظام الإدارة | Laravel (Eloquent + Migrations) |
| قاعدة البيانات المستهدفة | MySQL 8+ أو PostgreSQL 15+ |
| أعراف التسمية | snake_case، جمع، `id` = BIGINT UNSIGNED AI |
| الحذف | `softDeletes` فقط حيث يلزم، وبقية الجداول `RESTRICT` افتراضيًا |
| الطوابع الزمنية | `created_at`, `updated_at` على كل الجداول |

---

## 2. النطاقات السبعة

| # | النطاق | الجداول |
|---|---|---|
| A | الهوية والصلاحيات | users, roles, user_roles, author_applications |
| B | الكتالوج | categories, tags, books, book_authors, book_categories, book_tags |
| C | المحتوى والحقوق | book_versions, book_files, book_rights, book_samples |
| D | الاستحقاق والشراء | entitlements, orders, order_items, payment_attempts, refunds |
| E | التفاعل | reading_progress, favorites, reviews |
| F | الطلبات والإشعارات | book_requests, book_request_supports, notifications |
| G | الإشراف والتدقيق | moderation_cases, audit_logs |

---

## 3. مخطط العلاقات (Mermaid)

```mermaid
erDiagram
    users ||--o{ user_roles : ""
    roles ||--o{ user_roles : ""
    users ||--o{ author_applications : "submits"
    users ||--o{ book_authors : ""
    books ||--o{ book_authors : ""

    categories ||--o{ book_categories : ""
    books ||--o{ book_categories : ""
    categories ||--o{ categories : "parent"
    tags ||--o{ book_tags : ""
    books ||--o{ book_tags : ""

    books ||--o{ book_versions : "has"
    book_versions ||--o{ book_files : "contains"
    book_versions ||--o{ book_samples : "provides"
    books ||--o{ book_rights : "requires"

    users ||--o{ entitlements : "owns"
    books ||--o{ entitlements : "granted for"
    orders ||--o{ entitlements : "source"
    users ||--o{ orders : "places"
    orders ||--o{ order_items : "contains"
    books ||--o{ order_items : "in"
    orders ||--o{ payment_attempts : "attempted via"
    orders ||--o{ refunds : "may have"

    users ||--o{ reading_progress : "tracks"
    books ||--o{ reading_progress : "tracked by"
    users ||--o{ favorites : "saves"
    books ||--o{ favorites : "saved by"
    users ||--o{ reviews : "writes"
    books ||--o{ reviews : "receives"

    users ||--o{ book_requests : "requests"
    books ||--o{ book_requests : "fulfills"
    book_requests ||--o{ book_request_supports : "supported by"

    users ||--o{ notifications : "receives"
    users ||--o{ moderation_cases : "acts"
    users ||--o{ audit_logs : "acts"