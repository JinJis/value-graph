import { signIn } from "@/auth";

export default function SignIn() {
  const hasGoogle = Boolean(process.env.AUTH_GOOGLE_ID);
  const hasDev = process.env.AUTH_DEV_LOGIN === "true";
  return (
    <main className="center">
      <div className="card">
        <h1>ValueGraph</h1>
        <p>시장·종목·뉴스·경제, 무엇이든 물어보세요 — 출처와 함께 답합니다.</p>
        {hasGoogle && (
          <form action={async () => { "use server"; await signIn("google", { redirectTo: "/" }); }}>
            <button className="btn">Google로 로그인</button>
          </form>
        )}
        {hasDev && (
          <form action={async (fd: FormData) => { "use server"; await signIn("credentials", { email: String(fd.get("email") || ""), redirectTo: "/" }); }}>
            <input className="input" name="email" type="email" placeholder="dev@example.com" required />
            <button className="btn ghost">개발용 로그인</button>
          </form>
        )}
        {!hasGoogle && !hasDev && <p>로그인 제공자가 설정되지 않았습니다 (.env 참고).</p>}
      </div>
    </main>
  );
}
