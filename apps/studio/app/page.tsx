import Link from "next/link";

export default function Page() {
  return (
    <main
      style={{ maxWidth: 720, margin: "2rem auto", fontFamily: "system-ui" }}
    >
      <h1>ValueGraph Studio</h1>
      <p>
        Admin back-office. Build a theme, run CVE, process tickets, publish.
      </p>
      <p>
        <Link href="/themes">→ Themes</Link>
      </p>
    </main>
  );
}
