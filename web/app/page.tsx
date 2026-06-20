import { auth } from "@/auth";
import Chat from "@/components/Chat";
import SignIn from "@/components/SignIn";

export const dynamic = "force-dynamic";

export default async function Home() {
  const session = await auth();
  if (!session?.user?.email) return <SignIn />;
  return <Chat name={session.user.name ?? session.user.email} />;
}
