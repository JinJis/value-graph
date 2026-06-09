import Link from "next/link";

export default function Page() {
  return (
    <main
      style={{ maxWidth: 720, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <h1>ValueGraph Studio</h1>
      <p>Admin back-office for building and publishing a supply-chain graph.</p>
      <p style={{ color: "#475569" }}>
        <small>
          Each theme walks through 6 steps:{" "}
          <strong>
            Theme → Blueprint → Tickets → Financials → Build → Publish
          </strong>
          .
        </small>
      </p>
      <p>
        <Link href="/themes">→ Themes</Link>
        {" · "}
        <Link href="/jobs">→ CVE jobs</Link>
        {" · "}
        <Link href="/prompts">→ Prompts</Link>
      </p>
      <p style={{ color: "#475569" }}>
        <small>
          {/* Full-page nav to the engine's docs (served through the /engine proxy). */}
          <a href="/engine/">→ API docs &amp; database ERD</a>
        </small>
      </p>
    </main>
  );
}
