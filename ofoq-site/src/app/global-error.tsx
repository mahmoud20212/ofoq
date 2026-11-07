"use client"

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="ar" dir="rtl">
      <body>
        <main
          style={{
            minHeight: "100vh",
            display: "grid",
            placeItems: "center",
            background: "#080a12",
            color: "#fff",
            fontFamily: "Alexandria, sans-serif",
            padding: "24px",
            textAlign: "center",
          }}
        >
          <div>
            <p style={{ color: "#c9bcff" }}>أُفُق</p>
            <h1>تعذر تحميل هذه الصفحة</h1>
            <p style={{ color: "#b9b9ca" }}>
              حدث خطأ غير متوقع. يمكنك إعادة المحاولة دون فقدان رحلتك.
            </p>
            <button
              type="button"
              onClick={reset}
              style={{
                marginTop: "18px",
                border: 0,
                borderRadius: "999px",
                padding: "13px 22px",
                background: "linear-gradient(135deg, #6246d9, #2475e9)",
                color: "#fff",
                cursor: "pointer",
              }}
            >
              إعادة المحاولة
            </button>
          </div>
        </main>
      </body>
    </html>
  )
}
