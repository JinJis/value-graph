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
      </p>
    </main>
  );
}
