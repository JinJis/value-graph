import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";

// Google in production; an optional dev-login (any email) for local use without
// Google credentials (set AUTH_DEV_LOGIN=true).
const providers: any[] = [];
if (process.env.AUTH_GOOGLE_ID) providers.push(Google);
if (process.env.AUTH_DEV_LOGIN === "true") {
  providers.push(
    Credentials({
      name: "Dev",
      credentials: { email: { label: "Email", type: "email" } },
      authorize: (creds) => {
        const email = String(creds?.email || "");
        return email.includes("@") ? { id: email, email, name: email.split("@")[0] } : null;
      },
    }),
  );
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers,
  trustHost: true,
});
