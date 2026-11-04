
import { Link } from "react-router-dom";
import {
  UserRound,
  ShieldCheck,
  MonitorSmartphone,
  Grid2X2,
  BookOpen,
  GraduationCap,
  ArrowUpLeft,
  Sparkles,
  ChevronLeft,
} from "lucide-react";

import styles from "./MyPage.module.css";

const sections = [
  {
    title: "الملف الشخصي",
    description: "إدارة الاسم والبريد الإلكتروني وبيانات الحساب",
    path: "../",
    icon: UserRound,
  },
  {
    title: "الأمان وتسجيل الدخول",
    description: "تغيير كلمة المرور وإعدادات التحقق الثنائي",
    path: "../account-security/signingIn",
    icon: ShieldCheck,
  },
  {
    title: "الأجهزة والجلسات",
    description: "مراجعة الأجهزة والجلسات المرتبطة بحسابك",
    path: "../account-security/deviceActivity",
    icon: MonitorSmartphone,
  },
  {
    title: "التطبيقات المرتبطة",
    description: "عرض التطبيقات المتصلة بحساب أُفق",
    path: "../applications",
    icon: Grid2X2,
  },
];

const platforms = [
  {
    title: "أُفق ورق",
    description: "منصة لبيع وتبادل الكتب بين المستخدمين",
    icon: BookOpen,
    className: "books",
  },
  {
    title: "أُفق مسار",
    description: "منصة للتعليم الإلكتروني والدورات التدريبية",
    icon: GraduationCap,
    className: "learning",
  },
];

export const MyPage = () => {
  return (
    <div className={styles.dashboard} dir="rtl">
      {/* Welcome Banner */}
      <section className={styles.welcomeBanner}>
        <div className={styles.welcomeContent}>
          <span className={styles.eyebrow}>
            <Sparkles size={15} />
            أُفق | مركز الحسابات
          </span>

          <h1>مرحبًا بك في أُفق</h1>

          <p>
            حساب واحد يربطك بجميع منصات أُفق.
            يمكنك إدارة بياناتك وأمان حسابك من مكان واحد.
          </p>
        </div>

        <div className={styles.bannerDecoration}>
          <span className={styles.decorCircle} />
        </div>
      </section>

      {/* Account Management */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div>
            <h2>إدارة الحساب</h2>
            <p>كل ما تحتاجه للتحكم في حسابك وأمانه</p>
          </div>
        </div>

        <div className={styles.dashboardGrid}>
          {sections.map((section) => {
            const Icon = section.icon;

            return (
              <Link
                key={section.title}
                to={section.path}
                className={styles.dashboardCard}
              >
                <div className={styles.cardTop}>
                  <span className={styles.cardIcon}>
                    <Icon size={23} strokeWidth={1.8} />
                  </span>

                  <ChevronLeft
                    size={18}
                    className={styles.cardChevron}
                  />
                </div>

                <h3>{section.title}</h3>
                <p>{section.description}</p>

                <span className={styles.cardAction}>
                  إدارة
                  <ArrowUpLeft size={15} />
                </span>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Platforms */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div>
            <h2>منصات أُفق</h2>
            <p>استكشف منصاتنا باستخدام حسابك الموحد</p>
          </div>
        </div>

        <div className={styles.platformGrid}>
          {platforms.map((platform) => {
            const Icon = platform.icon;

            return (
              <div
                key={platform.title}
                className={`${styles.platformCard} ${
                  platform.className === "books"
                    ? styles.books
                    : styles.learning
                }`}
              >
                <span className={styles.platformIcon}>
                  <Icon size={26} strokeWidth={1.7} />
                </span>

                <div className={styles.platformContent}>
                  <h3>{platform.title}</h3>
                  <p>{platform.description}</p>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <footer className={styles.dashboardFooter}>
        <span>أُفق — حساب واحد، آفاق متعددة</span>
      </footer>
    </div>
  );
};
